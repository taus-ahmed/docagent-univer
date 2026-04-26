"""
DocAgent — Orchestrator
The central pipeline controller. Coordinates:
  Preprocessing → Classification → Extraction → Validation → Excel Output

Usage:
  orchestrator = Orchestrator(client_schema_path="schemas/clients/demo_accounting.yaml")
  result = orchestrator.process_folder("./input")
"""

import time
from pathlib import Path
from datetime import datetime
from typing import Optional
from dataclasses import dataclass, field

from rich.console import Console
from rich.table import Table
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TimeElapsedColumn
from rich.panel import Panel

from core.preprocessor import preprocess_file, get_supported_files, ProcessedDocument
from core.prompt_builder import PromptBuilder, ClientSchema, load_client_schema
from core.validator import validate_extraction, ValidationResult
from core.excel_writer import ExcelWriter
from connectors.llm_router import LLMRouter
from connectors.groq_client import LLMResponse
from storage.database import Database
from backend.engine.config import settings

console = Console()


@dataclass
class DocumentExtractionResult:
    """Result of processing a single document."""
    filename: str
    document_type: str = "unknown"
    classification_response: Optional[LLMResponse] = None
    extraction_response: Optional[LLMResponse] = None
    extracted_data: Optional[dict] = None
    validation: Optional[ValidationResult] = None
    success: bool = False
    error: str = ""
    processing_time_ms: float = 0


@dataclass
class BatchResult:
    """Result of processing a batch of documents."""
    total_docs: int = 0
    successful: int = 0
    failed: int = 0
    needs_review: int = 0
    results: list[DocumentExtractionResult] = field(default_factory=list)
    output_file: str = ""
    total_time_sec: float = 0
    client_name: str = ""


class Orchestrator:
    """Main pipeline controller."""

    def __init__(self, client_schema_path: str | Path):
        self.schema = load_client_schema(client_schema_path)
        self.prompt_builder = PromptBuilder(self.schema)
        self.llm = LLMRouter()
        self.db = Database()

        console.print(Panel(
            f"[bold green]DocAgent Initialized[/]\n"
            f"Client: [cyan]{self.schema.client_name}[/]\n"
            f"Document types: [yellow]{', '.join(self.schema.type_names)}[/]\n"
            f"Primary LLM: [magenta]{settings.PRIMARY_LLM}[/]",
            title="🤖 DocAgent",
            border_style="green",
        ))

    def process_folder(self, input_folder: str | Path, output_path: Optional[str | Path] = None) -> BatchResult:
        """Process all documents in a folder. This is the main entry point."""
        input_folder = Path(input_folder)
        if not input_folder.exists():
            raise FileNotFoundError(f"Input folder not found: {input_folder}")

        files = get_supported_files(input_folder)
        if not files:
            console.print("[yellow]No supported files found in folder.[/]")
            return BatchResult()

        # Set output path
        if output_path is None:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            output_path = settings.OUTPUT_FOLDER / f"extraction_{self.schema.client_id}_{timestamp}.xlsx"

        console.print(f"\n📁 Found [bold]{len(files)}[/] documents in [cyan]{input_folder}[/]")

        # Create job in database
        job_id = self.db.create_job(
            client_id=self.schema.client_id,
            input_folder=str(input_folder),
            total_docs=len(files),
        )

        # Process documents
        batch = BatchResult(total_docs=len(files), client_name=self.schema.client_name)
        excel = ExcelWriter()
        start_time = time.time()

        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
            TimeElapsedColumn(),
            console=console,
        ) as progress:
            task = progress.add_task("Processing documents...", total=len(files))

            for file_path in files:
                progress.update(task, description=f"Processing: {file_path.name[:40]}")

                result = self._process_single_document(file_path)
                batch.results.append(result)

                if result.success and result.extracted_data:
                    batch.successful += 1

                    # Get schema for this doc type
                    type_schema = self.schema.get_type_schema(result.document_type)
                    schema_fields = type_schema.get("fields", []) if type_schema else []
                    line_items_schema = type_schema.get("line_items", []) if type_schema else []

                    excel.add_extraction_result(
                        doc_type=result.document_type,
                        filename=result.filename,
                        extracted_data=result.extracted_data,
                        validation_result=result.validation,
                        schema_fields=schema_fields,
                        line_items_schema=line_items_schema,
                    )

                    if result.validation and result.validation.needs_review:
                        batch.needs_review += 1

                    # Save to database
                    self.db.add_document_result(
                        job_id=job_id,
                        filename=result.filename,
                        doc_type=result.document_type,
                        extracted=result.extracted_data,
                        validation=result.validation,
                        llm_response=result.extraction_response,
                    )
                else:
                    batch.failed += 1

                progress.advance(task)

        batch.total_time_sec = time.time() - start_time

        # Add summary sheet and save
        job_stats = {
            "total_docs": batch.total_docs,
            "successful": batch.successful,
            "failed": batch.failed,
            "needs_review": batch.needs_review,
            "total_time_sec": batch.total_time_sec,
            "client_name": self.schema.client_name,
            "primary_llm": settings.PRIMARY_LLM,
            "avg_confidence": self._calc_avg_confidence(batch.results),
        }
        excel.add_summary_sheet(job_stats)
        output_path = excel.save(output_path)
        batch.output_file = str(output_path)

        # Update job in database
        self.db.complete_job(job_id, str(output_path), job_stats)

        # Print summary
        self._print_summary(batch)

        return batch

    def process_files(self, file_paths: list[Path], output_path: Optional[str | Path] = None, progress_callback=None) -> BatchResult:
        """Process a list of specific files. Used by the dashboard for uploaded files."""
        if not file_paths:
            return BatchResult()

        if output_path is None:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            output_path = settings.OUTPUT_FOLDER / f"extraction_{self.schema.client_id}_{timestamp}.xlsx"

        job_id = self.db.create_job(
            client_id=self.schema.client_id,
            input_folder="uploaded",
            total_docs=len(file_paths),
        )

        batch = BatchResult(total_docs=len(file_paths), client_name=self.schema.client_name)
        excel = ExcelWriter()
        start_time = time.time()

        for i, file_path in enumerate(file_paths):
            if progress_callback:
                progress_callback(i, len(file_paths), file_path.name)

            result = self._process_single_document(file_path)
            batch.results.append(result)

            if result.success and result.extracted_data:
                batch.successful += 1
                type_schema = self.schema.get_type_schema(result.document_type)
                schema_fields = type_schema.get("fields", []) if type_schema else []
                line_items_schema = type_schema.get("line_items", []) if type_schema else []

                excel.add_extraction_result(
                    doc_type=result.document_type,
                    filename=result.filename,
                    extracted_data=result.extracted_data,
                    validation_result=result.validation,
                    schema_fields=schema_fields,
                    line_items_schema=line_items_schema,
                )

                if result.validation and result.validation.needs_review:
                    batch.needs_review += 1

                self.db.add_document_result(
                    job_id=job_id,
                    filename=result.filename,
                    doc_type=result.document_type,
                    extracted=result.extracted_data,
                    validation=result.validation,
                    llm_response=result.extraction_response,
                )
            else:
                batch.failed += 1

        batch.total_time_sec = time.time() - start_time

        job_stats = {
            "total_docs": batch.total_docs,
            "successful": batch.successful,
            "failed": batch.failed,
            "needs_review": batch.needs_review,
            "total_time_sec": batch.total_time_sec,
            "client_name": self.schema.client_name,
            "primary_llm": settings.PRIMARY_LLM,
            "avg_confidence": self._calc_avg_confidence(batch.results),
        }
        excel.add_summary_sheet(job_stats)
        output_path = excel.save(output_path)
        batch.output_file = str(output_path)

        self.db.complete_job(job_id, str(output_path), job_stats)

        return batch

    def _process_single_document(self, file_path: Path) -> DocumentExtractionResult:
        """Process a single document through the full pipeline."""
        result = DocumentExtractionResult(filename=file_path.name)
        start = time.time()

        try:
            # Step 1: Preprocess
            doc = preprocess_file(file_path)

            # Step 2: Classify (Pass 1)
            classification = self._classify_document(doc)
            result.classification_response = classification

            if not classification.success:
                result.error = f"Classification failed: {classification.error}"
                return result

            doc_type = classification.parsed_json.get("document_type", "other")
            result.document_type = doc_type

            # Step 3: Extract (Pass 2)
            extraction = self._extract_data(doc, doc_type)
            result.extraction_response = extraction

            if not extraction.success:
                result.error = f"Extraction failed: {extraction.error}"
                return result

            result.extracted_data = extraction.parsed_json

            # Step 4: Validate
            type_schema = self.schema.get_type_schema(doc_type)
            if type_schema:
                result.validation = validate_extraction(extraction.parsed_json, type_schema)
            else:
                result.validation = ValidationResult()

            result.success = True

        except Exception as e:
            result.error = f"Processing error: {str(e)}"
            console.print(f"  [red]✗ Error processing {file_path.name}: {e}[/]")

        result.processing_time_ms = (time.time() - start) * 1000
        return result

    def _classify_document(self, doc: ProcessedDocument) -> LLMResponse:
        """Pass 1: Classify the document type."""
        prompt = self.prompt_builder.build_classification_prompt()

        if doc.has_meaningful_text:
            return self.llm.classify(text=doc.extracted_text, prompt=prompt)
        elif doc.page_images_b64:
            return self.llm.classify(image_b64=doc.page_images_b64[0], prompt=prompt)
        else:
            return LLMResponse(raw_text="", success=False, error="No text or images available")

    def _extract_data(self, doc: ProcessedDocument, doc_type: str) -> LLMResponse:
        """Pass 2: Extract structured data using the matched schema."""
        use_vision = doc.needs_vision and bool(doc.page_images_b64)
        prompt = self.prompt_builder.build_extraction_prompt(doc_type, use_vision=use_vision)

        if use_vision:
            # For multi-page docs, process first page (can be extended to all pages)
            return self.llm.extract(image_b64=doc.page_images_b64[0], prompt=prompt)
        else:
            return self.llm.extract(text=doc.extracted_text, prompt=prompt)

    def _calc_avg_confidence(self, results: list[DocumentExtractionResult]) -> str:
        conf_map = {"high": 3, "medium": 2, "low": 1}
        scores = []
        for r in results:
            if r.extracted_data:
                conf = r.extracted_data.get("overall_confidence", "medium")
                scores.append(conf_map.get(conf, 2))
        if not scores:
            return "N/A"
        avg = sum(scores) / len(scores)
        if avg >= 2.5:
            return "High"
        elif avg >= 1.5:
            return "Medium"
        return "Low"

    def _print_summary(self, batch: BatchResult):
        """Print a formatted summary table."""
        console.print("\n")

        # Summary panel
        status_color = "green" if batch.failed == 0 else "yellow" if batch.failed < batch.total_docs else "red"
        console.print(Panel(
            f"[bold]Documents processed:[/] {batch.total_docs}\n"
            f"[green]✓ Successful:[/] {batch.successful}\n"
            f"[red]✗ Failed:[/] {batch.failed}\n"
            f"[yellow]⚠ Needs Review:[/] {batch.needs_review}\n"
            f"[dim]Time: {batch.total_time_sec:.1f}s | "
            f"Avg: {batch.total_time_sec/max(batch.total_docs, 1):.1f}s/doc[/]",
            title=f"📊 Extraction Complete",
            border_style=status_color,
        ))

        # Results table
        table = Table(title="Document Results", show_lines=True)
        table.add_column("File", style="cyan", max_width=35)
        table.add_column("Type", style="magenta")
        table.add_column("Confidence", justify="center")
        table.add_column("Status", justify="center")
        table.add_column("Time", justify="right")

        for r in batch.results:
            conf = r.extracted_data.get("overall_confidence", "?") if r.extracted_data else "?"
            conf_style = {"high": "[green]", "medium": "[yellow]", "low": "[red]"}.get(conf, "[dim]")

            status = "[green]✓[/]" if r.success else f"[red]✗ {r.error[:30]}[/]"
            if r.success and r.validation and r.validation.needs_review:
                status = "[yellow]⚠ Review[/]"

            table.add_row(
                r.filename[:35],
                r.document_type,
                f"{conf_style}{conf}[/]",
                status,
                f"{r.processing_time_ms:.0f}ms",
            )

        console.print(table)
        console.print(f"\n📄 Output saved to: [bold green]{batch.output_file}[/]\n")

        # LLM usage stats
        console.print(f"[dim]LLM calls — Groq: {self.llm.stats['groq_calls']} | "
                       f"Gemini: {self.llm.stats['gemini_calls']} | "
                       f"Failures: {self.llm.stats['failures']}[/]")