import { HttpAgent } from "@ag-ui/client";
import {
  CopilotChat,
  CopilotKit,
  useAgent,
  useAgentContext,
} from "@copilotkit/react-core/v2";
import "@copilotkit/react-core/v2/styles.css";

// Dev-only direct connection to the AG-UI endpoint — no Node runtime in
// between. The endpoint is a Django view (`just copilotkit-server`),
// proxied by Vite so the chat and the wizard share an origin.
const wizardAgent = new HttpAgent({ url: "/agent/" });

// The value demo: this profile is "already in the product" (think CRM or
// account data). It is exposed to the agent as context, so a one-line
// request from the user lets the agent fill most of a fourteen-step
// wizard without asking a single question the page can already answer.
const businessProfile = {
  company_name: "Analytical Engines Ltd",
  company_type: "limited company",
  companies_house_number: "AE123456",
  vat_registered: true,
  founded: "1837-12-10",
  employees: 12,
  fleet: [
    { registration: "AE01 CAB", approximate_value_gbp: 18000 },
    { registration: "AE02 CAB", approximate_value_gbp: 9500 },
  ],
  claims_last_five_years: [],
  contact_email: "ada@analyticalengines.example",
};

const styles = {
  page: {
    display: "grid",
    gridTemplateColumns: "1fr 420px",
    height: "100vh",
    margin: 0,
    fontFamily: "system-ui, sans-serif",
    color: "#1a202c",
  },
  panel: {
    padding: "2rem 2.5rem",
    overflowY: "auto",
    background: "#f7f8fa",
    borderRight: "1px solid #e2e5ea",
  },
  chat: { height: "100vh", overflow: "hidden" },
  muted: { color: "#697386" },
  card: {
    background: "#fff",
    border: "1px solid #e2e5ea",
    borderRadius: "8px",
    padding: "1rem 1.25rem",
    marginBottom: "1rem",
  },
  confirmation: {
    background: "#ecfdf3",
    border: "1px solid #b7e4c7",
    borderRadius: "8px",
    padding: "1rem 1.25rem",
    marginBottom: "1rem",
  },
  handoff: {
    background: "#fffbeb",
    border: "1px solid #fde68a",
    borderRadius: "8px",
    padding: "1rem 1.25rem",
    marginBottom: "1rem",
  },
  handoffLink: {
    display: "inline-block",
    marginTop: "0.5rem",
    padding: "0.5rem 1.1rem",
    borderRadius: "4px",
    background: "#2f5d8c",
    color: "#fff",
    fontWeight: 600,
    textDecoration: "none",
  },
  progress: {
    background: "#eff6ff",
    border: "1px solid #bfdbfe",
    borderRadius: "8px",
    padding: "0.75rem 1.25rem",
    marginBottom: "1rem",
  },
};

function StepBadge({ label, status }) {
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

function Outline({ entries, state }) {
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

function fieldCount(answers) {
  return Object.values(answers ?? {}).reduce(
    (total, fields) => total + Object.keys(fields).length,
    0,
  );
}

function WizardPanel() {
  // Everything in this card flows to the agent automatically — this is
  // the context it prefills from.
  useAgentContext({
    description: "The customer's business profile, from their account",
    value: businessProfile,
  });

  const { agent } = useAgent({ agentId: "default" });
  const state = agent.state ?? {};
  const filled = fieldCount(state.answers);
  const steps = Object.keys(state.answers ?? {}).length;

  return (
    <div style={styles.panel}>
      <h1 style={{ marginTop: 0 }}>Business insurance quote</h1>
      <p style={styles.muted}>
        Filled by hand this wizard is up to fourteen steps. Ask the chat for
        a quote and it fills everything your profile already answers, then
        asks only for the rest.
      </p>

      {state.handoff_url && (
        <div style={styles.handoff}>
          <strong>Your turn</strong>
          <p style={{ margin: "0.35rem 0 0" }}>
            Everything is filled in. Review your answers, change anything
            that looks wrong, and confirm — the copilot won’t submit for
            you.
          </p>
          <a style={styles.handoffLink} href={state.handoff_url}>
            Review and finish →
          </a>
        </div>
      )}

      {filled > 0 && (
        <div style={styles.progress}>
          <strong>{filled}</strong> answers across <strong>{steps}</strong>{" "}
          steps filled by your copilot so far
          {state.step ? (
            <>
              {" "}
              — now on <strong>{state.step}</strong>
            </>
          ) : null}
          .
        </div>
      )}

      <div style={styles.card}>
        <h3 style={{ marginTop: 0 }}>Your business profile</h3>
        <p style={{ ...styles.muted, marginTop: 0 }}>
          Already on file — the copilot reads this instead of asking you.
        </p>
        <table style={{ borderCollapse: "collapse" }}>
          <tbody>
            {Object.entries(businessProfile).map(([key, value]) => (
              <tr key={key}>
                <td style={{ padding: "0.15rem 1rem 0.15rem 0", ...styles.muted }}>
                  {key.replaceAll("_", " ")}
                </td>
                <td style={{ padding: "0.15rem 0" }}>
                  {typeof value === "object" ? JSON.stringify(value) : String(value)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {state.outline && (
        <div style={styles.card}>
          <h3 style={{ marginTop: 0 }}>The journey</h3>
          <Outline entries={state.outline} state={state} />
        </div>
      )}

      <div style={styles.card}>
        <h3 style={{ marginTop: 0 }}>Answers so far</h3>
        {state.answers && Object.keys(state.answers).length > 0 ? (
          <table style={{ borderCollapse: "collapse" }}>
            <tbody>
              {Object.entries(state.answers).map(([step, fields]) =>
                Object.entries(fields).map(([field, value]) => (
                  <tr key={`${step}.${field}`}>
                    <td style={{ padding: "0.2rem 1rem 0.2rem 0", ...styles.muted }}>
                      {step} · {field}
                    </td>
                    <td style={{ padding: "0.2rem 0" }}>{String(value)}</td>
                  </tr>
                )),
              )}
            </tbody>
          </table>
        ) : (
          <p style={{ ...styles.muted, marginBottom: 0 }}>
            Nothing yet — try “Get me a quote: property and vehicle cover,
            £500 excess, starting 1 September.”
          </p>
        )}
      </div>
    </div>
  );
}

export default function App() {
  return (
    <CopilotKit agents__unsafe_dev_only={{ default: wizardAgent }}>
      <div style={styles.page}>
        <WizardPanel />
        <div style={styles.chat}>
          <CopilotChat />
        </div>
      </div>
    </CopilotKit>
  );
}
