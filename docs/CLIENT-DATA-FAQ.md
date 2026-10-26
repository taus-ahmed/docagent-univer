# Your data in DocAgent — questions firms ask

Plain answers, taken from the code as of round 14. ⚠ **VERIFY** marks a
statement about a provider (Railway, Cloudflare, Google) that cannot be
checked from the code. **Tauseef confirms every VERIFY before this page is
shown to any client.**

**What do you keep?** The documents you upload; the values read from them
(with the quote and page each came from); your edits and review marks; your
templates; and, for some jobs, the model's raw answer. Account details:
username, display name, optional email, a salted password hash. Nothing else.

**Where does it live?** Accounts, results and templates in a PostgreSQL
database on Railway (region: the project's region ⚠ VERIFY). Uploaded files in
a private Cloudflare R2 bucket (location ⚠ VERIFY), or — if R2 is not
configured — briefly on the server's own disk, where they are lost at the next
update. To be read, each document's text and page images are sent to Google's
Gemini API.

**Who can see it?** Only people in your firm, by role: your administrators and
reviewers see all your firm's jobs; a user sees their own. Another firm cannot
see, find or even confirm the existence of anything of yours — an id of yours
answers "not found" to them exactly like an id that does not exist. The
operator (the platform administrator) can see every firm's data to run the
service.

**How are firms kept apart?** Every record carries your firm's id, taken from
your sign-in, never from what a request says. Every stored file lives under
your firm's own folder. An automated test signs in as each role of a second
firm and tries every function of the application against your records; it
runs before every release, and a new function without such a test fails the
release.

**Does the model provider train on my documents?** Google's terms for the paid
Gemini API say prompts and responses are not used to improve its products; the
free tier may be (⚠ VERIFY the current terms, and that the production key is
on a paid, billing-enabled project). Google may keep requests for a limited
time for abuse monitoring (⚠ VERIFY the period).

**Is it encrypted?** In transit: HTTPS between your browser, the server, the
bucket and Google. At rest: R2 encrypts objects by default (⚠ VERIFY);
Railway's database storage (⚠ VERIFY). The application adds no encryption of
its own. Passwords are stored only as bcrypt hashes.

**How long do you keep it?** Until it is deleted. If the operator sets a
retention period, every job is deleted automatically that many days after it
finishes (one period for all firms today). A deleted job keeps only an empty
record (date, counts) so your history and billing still add up.

**Can we delete our data?** Yes. A user can delete their own job; your
administrator can delete any job in your firm. Deletion removes the files, the
extracted values, the review marks and the cached page images, and is checked
before it is reported done. It cannot be undone. Offboarding a whole firm is
done by the operator.

**What about backups?** Database backups (⚠ VERIFY schedule and how long they
are kept) contain deleted data until they expire. Deleted files are not kept:
the bucket keeps no old versions (⚠ VERIFY).

**What happens when someone leaves our firm?** Your administrator deactivates
their account: they cannot sign in, and any session they had stops working at
once. Their jobs stay with your firm.

**What do your logs contain?** Ids and counts — never your file names, values
or firm name. A document appears as an anonymous code.

**Will a wrong value reach our spreadsheet silently?** A value is marked
"verified" only when its exact words were found on the page. Anything read from
a scan, anything that failed a check, and anything a person still owes a look
is marked in the results and in the exported workbook, with the reason.
