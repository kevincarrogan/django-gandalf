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
