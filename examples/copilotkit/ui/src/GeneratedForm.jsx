import { useHumanInTheLoop } from "@copilotkit/react-core/v2";
import React from "react";
import { z } from "zod";

// A form the agent draws, rendered where the conversation is.
//
// The agent already knows every step of the wizard and the schema of each
// one — it gets an outline back before it starts, and a schema back from
// every tool it calls. What it does *not* have is a way to ask for several
// things at once in a shape that suits the person answering. Chat is a
// single-file queue: one question, one answer, repeat. For somebody who
// finds that hard — because the words are unfamiliar, because holding the
// thread costs them something, because typing is slow — the better answer
// is often a small form with three fields on it and an explanation beside
// each.
//
// So this is a second way for the agent to ask, and it chooses which to
// use. Nothing here decides for it, and nothing here knows what a quote
// is: it takes a description of a form and returns what somebody typed
// into it. The agent maps that onto steps with the tools it already has,
// and every value is re-proved by the walk exactly as if it had been typed
// into the chat — because as far as gandalf is concerned, it was.
//
// What this file *does* own is the widgets. The agent picks the fields,
// their order, their grouping and their words; the markup is ours, so a
// group of choices is a real `fieldset` with a `legend`, help text is tied
// to its input with `aria-describedby`, and every control has a label. A
// form generated per person is only worth having if it is well built, and
// that is not something to leave to a sentence in a prompt.

const OPTION = z.object({
  value: z.string().describe("The value to give back for this option."),
  label: z.string().describe("What the person reads."),
  description: z
    .string()
    .optional()
    .describe("A line under the option, where it needs explaining."),
});

const FIELD = z.object({
  name: z
    .string()
    .describe(
      "Your key for this answer. It comes back under this name, so use " +
        "the wizard's own field name where you mean to place it directly.",
    ),
  label: z.string().describe("The question, as the person should read it."),
  help: z
    .string()
    .optional()
    .describe("A line under the question: an example, or what it is for."),
  control: z
    .enum([
      "text",
      "longtext",
      "number",
      "date",
      "email",
      "tel",
      "choice",
      "multichoice",
      "yesno",
    ])
    .describe(
      "How to ask it. `choice` is one of several, `multichoice` is any " +
        "number of them, `yesno` is a yes/no pair.",
    ),
  options: z
    .array(OPTION)
    .optional()
    .describe("Required for `choice` and `multichoice`."),
  required: z.boolean().optional(),
  placeholder: z.string().optional(),
});

export const FORM_SPEC = z.object({
  title: z.string().optional().describe("A heading for the form."),
  intro: z
    .string()
    .optional()
    .describe("A sentence above the fields, saying what this is for."),
  fields: z.array(FIELD).min(1),
  submitLabel: z.string().optional().describe("Defaults to “Send”."),
});

const styles = {
  card: {
    border: "1px solid #d7dde3",
    borderRadius: "10px",
    background: "#fff",
    padding: "1rem 1.15rem 1.15rem",
    margin: "0.25rem 0",
    maxWidth: "34rem",
  },
  title: { margin: "0 0 0.25rem", fontSize: "1rem", fontWeight: 600 },
  intro: { margin: "0 0 0.9rem", color: "#5b6c7a", fontSize: "0.9rem" },
  field: { border: 0, padding: 0, margin: "0 0 1.1rem", minWidth: 0 },
  label: {
    display: "block",
    fontWeight: 600,
    fontSize: "0.93rem",
    marginBottom: "0.25rem",
  },
  help: { color: "#5b6c7a", fontSize: "0.82rem", margin: "0 0 0.4rem" },
  input: {
    font: "inherit",
    padding: "0.5rem 0.6rem",
    border: "1px solid #d7dde3",
    borderRadius: "6px",
    width: "100%",
    boxSizing: "border-box",
  },
  options: { display: "flex", flexDirection: "column", gap: "0.4rem" },
  option: {
    display: "flex",
    alignItems: "flex-start",
    gap: "0.55rem",
    border: "1px solid #d7dde3",
    borderRadius: "6px",
    padding: "0.45rem 0.6rem",
    cursor: "pointer",
    fontSize: "0.92rem",
  },
  optionNote: { display: "block", color: "#5b6c7a", fontSize: "0.8rem" },
  submit: {
    font: "inherit",
    fontWeight: 600,
    background: "#2f5d8c",
    color: "#fff",
    border: 0,
    borderRadius: "6px",
    padding: "0.55rem 1.2rem",
    cursor: "pointer",
  },
  done: { color: "#5b6c7a", fontSize: "0.88rem", margin: 0 },
};

function initialValues(fields) {
  const values = {};
  for (const field of fields ?? []) {
    values[field.name] = field.control === "multichoice" ? [] : "";
  }
  return values;
}

function Field({ field, value, onChange }) {
  const id = `gf-${field.name}`;
  const helpId = field.help ? `${id}-help` : undefined;
  const help = field.help ? (
    <p style={styles.help} id={helpId}>
      {field.help}
    </p>
  ) : null;

  // A group of choices is a group, and says so. The legend is the question
  // — which is what a screen reader announces before each option, and what
  // makes "£500" mean something on its own.
  if (field.control === "choice" || field.control === "yesno") {
    const options =
      field.control === "yesno"
        ? [
            { value: "yes", label: "Yes" },
            { value: "no", label: "No" },
          ]
        : (field.options ?? []);
    return (
      <fieldset style={styles.field}>
        <legend style={styles.label}>{field.label}</legend>
        {help}
        <div style={styles.options}>
          {options.map((option) => (
            <label key={option.value} style={styles.option}>
              <input
                type="radio"
                name={id}
                value={option.value}
                checked={value === option.value}
                aria-describedby={helpId}
                onChange={() => onChange(option.value)}
              />
              <span>
                {option.label}
                {option.description && (
                  <span style={styles.optionNote}>{option.description}</span>
                )}
              </span>
            </label>
          ))}
        </div>
      </fieldset>
    );
  }

  if (field.control === "multichoice") {
    const chosen = Array.isArray(value) ? value : [];
    return (
      <fieldset style={styles.field}>
        <legend style={styles.label}>{field.label}</legend>
        {help}
        <div style={styles.options}>
          {(field.options ?? []).map((option) => (
            <label key={option.value} style={styles.option}>
              <input
                type="checkbox"
                value={option.value}
                checked={chosen.includes(option.value)}
                aria-describedby={helpId}
                onChange={() =>
                  onChange(
                    chosen.includes(option.value)
                      ? chosen.filter((each) => each !== option.value)
                      : [...chosen, option.value],
                  )
                }
              />
              <span>
                {option.label}
                {option.description && (
                  <span style={styles.optionNote}>{option.description}</span>
                )}
              </span>
            </label>
          ))}
        </div>
      </fieldset>
    );
  }

  const types = {
    text: "text",
    longtext: "textarea",
    number: "number",
    date: "date",
    email: "email",
    tel: "tel",
  };
  const type = types[field.control] ?? "text";

  return (
    <div style={styles.field}>
      <label style={styles.label} htmlFor={id}>
        {field.label}
      </label>
      {help}
      {type === "textarea" ? (
        <textarea
          id={id}
          rows={3}
          style={styles.input}
          value={value}
          placeholder={field.placeholder}
          aria-describedby={helpId}
          required={field.required}
          onChange={(event) => onChange(event.target.value)}
        />
      ) : (
        <input
          id={id}
          type={type}
          style={styles.input}
          value={value}
          placeholder={field.placeholder}
          aria-describedby={helpId}
          required={field.required}
          onChange={(event) => onChange(event.target.value)}
        />
      )}
    </div>
  );
}

function GeneratedForm({ args, status, respond }) {
  const fields = args?.fields ?? [];
  const [values, setValues] = React.useState(() => initialValues(fields));
  const [sent, setSent] = React.useState(false);

  // The args stream in a token at a time, so the field list is still
  // growing while the model writes it. Seed any field that appears after
  // the first render rather than resetting what somebody has already
  // started typing.
  React.useEffect(() => {
    setValues((current) => {
      const missing = fields.filter((field) => !(field.name in current));
      if (missing.length === 0) return current;
      return { ...current, ...initialValues(missing) };
    });
  }, [fields.map((field) => field.name).join(" ")]);

  if (status === "inProgress") {
    return (
      <div style={styles.card}>
        <p style={styles.done}>Putting a form together…</p>
      </div>
    );
  }

  if (status === "complete" || sent) {
    return (
      <div style={styles.card}>
        <p style={styles.done}>Thanks — sent.</p>
      </div>
    );
  }

  return (
    <form
      style={styles.card}
      onSubmit={(event) => {
        event.preventDefault();
        setSent(true);
        respond({ submitted: true, answers: values });
      }}
    >
      {args.title && <h3 style={styles.title}>{args.title}</h3>}
      {args.intro && <p style={styles.intro}>{args.intro}</p>}
      {fields.map((field) => (
        <Field
          key={field.name}
          field={field}
          value={values[field.name] ?? ""}
          onChange={(next) =>
            setValues((current) => ({ ...current, [field.name]: next }))
          }
        />
      ))}
      <button type="submit" style={styles.submit}>
        {args.submitLabel || "Send"}
      </button>
    </form>
  );
}

/** Give the agent a second way to ask: a form it designs itself. */
export function useGeneratedForm() {
  useHumanInTheLoop({
    name: "collect_with_a_form",
    description:
      "Draw a form and show it to the person, instead of asking in chat. " +
      "You choose the fields, their order, their wording and how each one " +
      "is asked. Use it when several answers are wanted at once, when a " +
      "question is easier to pick from than to describe, or when somebody " +
      "has told you that chatting back and forth is hard for them. The " +
      "answers come back under the names you gave, and you place them with " +
      "the wizard's own tools afterwards — this only collects.",
    parameters: FORM_SPEC,
    render: GeneratedForm,
  });
}
