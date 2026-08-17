import { HttpAgent } from "@ag-ui/client";
import {
  CopilotChat,
  CopilotKit,
  useAgent,
  useCopilotKit,
} from "@copilotkit/react-core/v2";
import "@copilotkit/react-core/v2/styles.css";
import React, { useEffect, useState } from "react";

import { useGeneratedForm } from "./GeneratedForm.jsx";
import { inspectorEnabled } from "./inspector.js";
import { Outline } from "./journey.jsx";
import { styles } from "./styles.js";

const adaptiveAgent = new HttpAgent({ url: "/adaptive-agent/" });

// The run is an ordinary `HybridQuoteViewSet` run — the adaptive endpoint
// drives the same wizard as `/agent/` — so its bare run URL is the wizard's
// own, and lands on whichever step the walk has stopped at. Vite proxies
// `/quote` through to Django, so this is one origin like everything else.
const runUrl = (runId) => `/quote/${runId}/`;

// Openers that lead somewhere different, and the two at the top are the
// ones this was actually driven against — the same tool and the same
// wizard produced a seventeen-field form for the first and a four-field
// one for the second, which is the whole point and is easier to believe
// having watched it happen twice.
const OPENERS = [
  {
    said: (
      "I've never bought insurance before and I find these back-and-forth " +
      "chats really hard. Can you just give me things to fill in?"
    ),
    got: "flattened all fourteen steps into one form",
  },
  {
    said: (
      "I'm getting business insurance for the first time and I genuinely " +
      "don't know what any of these words mean. Please go slowly and " +
      "explain things."
    ),
    got: "explained first, then asked four questions",
  },
  {
    said: "I find typing hard — can you give me things to pick from?",
    got: "prefers choices over free text",
  },
  {
    said: "I need a quote for my business.",
    got: "no stated need — it just talks",
  },
];

function Openers({ agent }) {
  const { copilotkit } = useCopilotKit();
  const [sent, setSent] = useState(false);

  // Through `copilotkit.runAgent` rather than `agent.runAgent()`, which is
  // the difference between this working and not. The raw agent posts what
  // it holds; the core is what attaches the frontend tools registered on
  // the page — so calling the agent directly sends `tools: []`, the model
  // never learns it can draw a form, and it describes one in prose
  // instead. Which looks exactly like the model deciding not to.
  const send = async (said) => {
    setSent(true);
    agent.addMessage({ id: crypto.randomUUID(), role: "user", content: said });
    await copilotkit.runAgent({ agent });
  };

  return (
    <div style={styles.card}>
      <h3 style={{ marginTop: 0 }}>Try saying</h3>
      <p style={{ ...styles.muted, marginTop: 0 }}>
        Click one to send it. What it draws is its decision each time — the
        same wizard, the same tool, a different form.
      </p>
      <div style={{ display: "flex", flexDirection: "column", gap: "0.5rem" }}>
        {OPENERS.map(({ said, got }) => (
          <button
            key={said}
            type="button"
            style={styles.opener}
            disabled={sent}
            onClick={() => send(said)}
          >
            <span>“{said}”</span>
            <span style={styles.openerNote}>{got}</span>
          </button>
        ))}
      </div>
      {sent && (
        <p style={{ ...styles.muted, margin: "0.6rem 0 0" }}>
          Reload the page to start another conversation.
        </p>
      )}
    </div>
  );
}

function Panel() {
  const { agent } = useAgent({ agentId: "default" });
  const state = agent.state ?? {};
  const filled = Object.keys(state.answers ?? {}).length;

  return (
    <div style={styles.panel}>
      <h1 style={{ marginTop: 0 }}>A copilot that draws its own forms</h1>
      <p style={styles.muted}>
        Chat is a queue: one question, one answer, repeat. Tell this one how
        you would rather be asked and it stops queuing — it designs a form,
        shows it to you in the conversation, and fills the quote from what
        you put in it. It reads the wizard's shape first, so the options it
        offers are the wizard's own.
      </p>

      <Openers agent={agent} />

      {state.run_id && (
        <div style={styles.card}>
          <h3 style={{ marginTop: 0 }}>The same run, as an ordinary form</h3>
          <p style={{ ...styles.muted, marginTop: 0 }}>
            Whatever the agent drew, the answers went onto a normal gandalf
            run — same id, same storage, same walk. This is that run in the
            wizard's own Django pages, with none of the above involved.
          </p>
          <p style={{ margin: 0 }}>
            <a style={styles.handoffLink} href={runUrl(state.run_id)}>
              Open in the Django form →
            </a>
          </p>
        </div>
      )}

      {state.handoff_url && (
        <div style={styles.handoff}>
          <strong>Your turn</strong>
          <p style={{ margin: "0.35rem 0 0" }}>
            However it collected them, the answers are on an ordinary run.
            Check them over and confirm — the copilot won’t submit for you.
          </p>
          <a style={styles.handoffLink} href={state.handoff_url}>
            Review and finish →
          </a>
        </div>
      )}

      {state.outline && (
        <div style={styles.card}>
          <h3 style={{ marginTop: 0 }}>The journey</h3>
          <Outline entries={state.outline} state={state} />
        </div>
      )}

      <div style={styles.card}>
        <h3 style={{ marginTop: 0 }}>Answers so far</h3>
        {filled > 0 ? (
          <table style={{ borderCollapse: "collapse" }}>
            <tbody>
              {Object.entries(state.answers).map(([step, fields]) =>
                Object.entries(fields).map(([field, value]) => (
                  <tr key={`${step}.${field}`}>
                    <td
                      style={{
                        padding: "0.2rem 1rem 0.2rem 0",
                        ...styles.muted,
                      }}
                    >
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
            Nothing yet. Whatever the form looked like, what lands here is an
            ordinary answer on an ordinary run.
          </p>
        )}
      </div>

      <p style={styles.muted}>
        <a href="#licence">the driving licence check →</a>
      </p>
    </div>
  );
}

// The one thing worth keeping on screen when the panel is folded away:
// the form is the other half of the demo, and hiding the panel to watch a
// bare conversation should not cost you the way into it.
function FormLink() {
  const { agent } = useAgent({ agentId: "default" });
  const runId = agent.state?.run_id;
  if (!runId) return null;
  return (
    <a style={styles.cornerLink} href={runUrl(runId)}>
      Open in the Django form →
    </a>
  );
}

// Said before anything happens, because the interesting behaviour is
// behind somebody volunteering how they would rather be asked, and an
// empty chat box asks for nothing. It names both ways of doing this so
// that saying "just give me a form" is an obvious thing to say rather than
// a lucky guess.
//
// Added to the conversation rather than rendered above it, so it costs an
// assistant turn in the context — which is honest, because it is a thing
// the assistant said.
const GREETING = [
  "I can sort out a business insurance quote for you.",
  "It is a long one — fourteen steps filled in by hand — so tell me how",
  "you would rather do it. I can ask as we talk, or put together a form",
  "with everything on it at once. If the wording is unfamiliar, say so and",
  "I will explain as I go.",
].join(" ");

// Inside `CopilotKit`, because registering a tool needs its context — and
// beside the chat, because that is where the tool renders.
function Chat({ alone }) {
  useGeneratedForm();
  const { agent } = useAgent({ agentId: "default" });

  useEffect(() => {
    if (agent.messages?.length) return;
    agent.addMessage({
      id: crypto.randomUUID(),
      role: "assistant",
      content: GREETING,
    });
  }, [agent]);

  return (
    <div style={{ ...styles.chat, ...(alone ? styles.chatAlone : {}) }}>
      <CopilotChat
        labels={{
          chatInputPlaceholder:
            "Ask for a quote — or say how you'd rather be asked…",
        }}
      />
    </div>
  );
}

export default function Adaptive() {
  // On by default here, unlike the photo demos: the openers live in it,
  // and the thing worth watching is the form the agent draws, which is in
  // the chat either way. Collapse it to see what somebody using this would
  // actually see — a conversation, and nothing else.
  const [panel, setPanel] = useState(true);

  return (
    <CopilotKit
      agents__unsafe_dev_only={{ default: adaptiveAgent }}
      enableInspector={inspectorEnabled}
    >
      <div
        style={{
          ...styles.page,
          gridTemplateColumns: panel ? "1fr 480px" : "1fr",
        }}
      >
        {panel && <Panel />}
        <Chat alone={!panel} />
      </div>
      <FormLink />
      <button style={styles.debugToggle} onClick={() => setPanel(!panel)}>
        {panel ? "Hide panel" : "Show panel"}
      </button>
    </CopilotKit>
  );
}
