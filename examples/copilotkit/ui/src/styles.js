// Shared between the two demos on this page — the quote and the licence
// check — because they are the same layout with a different panel in it.

export const styles = {
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
  // A chat reads badly the full width of a monitor — the eye loses the
  // line. Centred in whatever column it is given, so the same style works
  // beside the run panel and on its own.
  chatAlone: {
    maxWidth: "620px",
    width: "100%",
    margin: "0 auto",
    borderLeft: "1px solid #e2e5ea",
    borderRight: "1px solid #e2e5ea",
  },
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
  debugToggle: {
    position: "fixed",
    top: "0.75rem",
    // Clear of CopilotKit's own dev inspector, which floats a 4rem button
    // in the top-right corner at the highest z-index there is. At 0.75rem
    // this button sat underneath it and half of it could not be clicked —
    // which is exactly what it looks like when a click handler is broken.
    right: "5rem",
    zIndex: 10,
    padding: "0.3rem 0.7rem",
    borderRadius: "4px",
    border: "1px solid #e2e5ea",
    background: "#fff",
    color: "#697386",
    fontSize: "0.8rem",
    cursor: "pointer",
  },
  // A canned opening line, clickable. Left-aligned and full width because
  // these are sentences rather than labels, and a centred sentence that
  // wraps is hard to read down a column of them.
  opener: {
    display: "flex",
    flexDirection: "column",
    gap: "0.2rem",
    textAlign: "left",
    font: "inherit",
    fontSize: "0.9rem",
    background: "#fff",
    border: "1px solid #e2e5ea",
    borderRadius: "6px",
    padding: "0.6rem 0.75rem",
    cursor: "pointer",
    width: "100%",
  },
  openerNote: { color: "#697386", fontSize: "0.78rem" },
  // Beside the panel toggle, clear of it and of CopilotKit's own inspector
  // button — see `debugToggle` below for why anything up here needs saying
  // out loud about what it is sitting next to.
  cornerLink: {
    position: "fixed",
    top: "0.75rem",
    right: "11.5rem",
    zIndex: 10,
    padding: "0.3rem 0.7rem",
    borderRadius: "4px",
    border: "1px solid #e2e5ea",
    background: "#fff",
    color: "#2f5d8c",
    fontSize: "0.8rem",
    fontWeight: 600,
    textDecoration: "none",
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
