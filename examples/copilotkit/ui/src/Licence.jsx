import { PhotoDemo } from "./PhotoDemo.jsx";

// The wizard behind this one has a file step, so the scan it is sent is
// kept on the run as an answer in its own right.
export default function Licence() {
  return (
    <PhotoDemo
      url="/licence-agent/"
      title="Driving licence check"
      prompt="Here is a photo of my driving licence. Please fill in the check."
      greeting={[
        "I can check a driving licence for you. Send me a photo of the front",
        "of the card and I'll keep it with your check, read the details off",
        "it, and hand it back for you to confirm.",
      ].join(" ")}
      labels={{
        chatInputPlaceholder: "Send a photo of your licence, or type a message…",
      }}
      blurb={
        "Photograph the front of the card. The agent attaches the picture to " +
        "the run, reads the details off it and fills them in; you check them " +
        "and confirm. It never confirms for you — it can misread a character, " +
        "and that looks exactly like getting it right."
      }
      emptyJourney="The agent maps this out when it starts — three steps, and only the last one is yours."
    />
  );
}
