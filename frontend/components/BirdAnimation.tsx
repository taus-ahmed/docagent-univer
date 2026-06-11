"use client";

import { useEffect } from "react";

export default function BirdAnimation({ onDone }: { onDone: () => void }) {
  useEffect(() => {
    const t = setTimeout(onDone, 1900);
    return () => clearTimeout(t);
  }, [onDone]);

  return (
    <>
      <style>{`
        @keyframes birdFly {
          0%   { transform: translate(0, 0);                        opacity: 0; }
          8%   { opacity: 1; }
          88%  { opacity: 1; }
          100% { transform: translate(calc(100vw + 180px), -24vh);  opacity: 0; }
        }
        .bird-wrap {
          position: fixed;
          left: -180px;
          top: 44vh;
          z-index: 9999;
          pointer-events: none;
          animation: birdFly 1.9s cubic-bezier(0.22, 0.8, 0.38, 1) forwards;
          will-change: transform, opacity;
          filter: drop-shadow(0 4px 10px rgba(0, 0, 0, 0.18));
        }
      `}</style>
      <div className="bird-wrap">
        <svg
          width="84"
          height="58"
          viewBox="-42 -29 84 58"
          xmlns="http://www.w3.org/2000/svg"
          aria-hidden="true"
        >
          {/* Wings — SMIL morph: level → up → down → level */}
          <path
            d="M -26 2 Q -10 -10 0 0 Q 10 -10 26 2"
            fill="none"
            stroke="#1e2130"
            strokeWidth="3.8"
            strokeLinecap="round"
            strokeLinejoin="round"
          >
            <animate
              attributeName="d"
              values={[
                "M -26 2 Q -10 -10 0 0 Q 10 -10 26 2",
                "M -26 -11 Q -10 -19 0  0 Q 10 -19 26 -11",
                "M -26  5 Q -10   1 0  0 Q 10   1 26  5",
                "M -26 2 Q -10 -10 0 0 Q 10 -10 26 2",
              ].join(";")}
              dur="0.4s"
              repeatCount="indefinite"
            />
          </path>

          {/* Body */}
          <ellipse cx="2" cy="5" rx="9.5" ry="4.5" fill="#1e2130" />

          {/* Head */}
          <circle cx="11" cy="1" r="5" fill="#1e2130" />

          {/* Eye */}
          <circle cx="12.8" cy="0" r="1.1" fill="#f5f6f8" />

          {/* Beak */}
          <line
            x1="14.5" y1="1.2"
            x2="21"   y2="2.8"
            stroke="#4f46e5"
            strokeWidth="2.4"
            strokeLinecap="round"
          />

          {/* Tail feathers */}
          <path
            d="M -10 6 L -21 3 M -10 6 L -19 12"
            stroke="#1e2130"
            strokeWidth="2.4"
            strokeLinecap="round"
            fill="none"
          />
        </svg>
      </div>
    </>
  );
}
