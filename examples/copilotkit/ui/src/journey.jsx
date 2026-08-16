// The run's shape, as the agent reported it. Shared by both demos: a
// three-step licence check and a fourteen-step quote want the same
// picture, and it is the picture that makes a handover legible — you can
// see which step the agent stopped at and what is left for you.
//
// `state.outline` only exists once the agent has called `get_outline`, so
// its absence is a fact about the conversation rather than about the
// wizard, and the panels say so rather than hiding the card.

// Imported although nothing here names it: Vite is transforming JSX with
// the classic runtime, so a tag compiles to `React.createElement` and
// needs React in scope.
import React from "react";

export function StepBadge({ label, status }) {
  const palette = {
    answered: { background: "#ecfdf3", border: "#b7e4c7" },
    current: { background: "#eff6ff", border: "#bfdbfe" },
    pending: { background: "#fff", border: "#e2e5ea" },
  }[status];
  return (
    <span
      style={{
        display: "inline-block",
        padding: "0.15rem 0.6rem",
        margin: "0.15rem 0.3rem 0.15rem 0",
        borderRadius: "999px",
        fontSize: "0.85rem",
        background: palette.background,
        border: `1px solid ${palette.border}`,
      }}
    >
      {status === "answered" ? "✓ " : ""}
      {label}
    </span>
  );
}

export function Outline({ entries, state }) {
  return entries.map((entry, index) => {
    if (entry.kind === "step") {
      const status =
        state.answers && entry.step in state.answers
          ? "answered"
          : entry.step === state.step
            ? "current"
            : "pending";
      return <StepBadge key={index} label={entry.step} status={status} />;
    }
    if (entry.kind === "branch") {
      return (
        <span key={index} style={{ margin: "0 0.3rem" }}>
          {"{ "}
          {entry.arms.map((arm, armIndex) => (
            <span key={armIndex} title={arm.description ?? arm.when ?? ""}>
              <em style={{ color: "#697386", fontSize: "0.8rem" }}>
                if {arm.when}:{" "}
              </em>
              <Outline entries={arm.steps} state={state} />
              {" | "}
            </span>
          ))}
          <Outline entries={entry.default} state={state} />
          {" }"}
        </span>
      );
    }
    return (
      <StepBadge key={index} label="…grows from an answer" status="pending" />
    );
  });
}
