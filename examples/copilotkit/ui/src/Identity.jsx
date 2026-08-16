import { PhotoDemo } from "./PhotoDemo.jsx";

// The wizard behind this one has no file step at all — five pages of
// plain text, one question each, and nowhere a document could be stored.
// The photograph is only ever read, which is the case that needs nothing
// from the library and is much the more common one.
export default function Identity() {
  return (
    <PhotoDemo
      url="/identity-agent/"
      title="Identity check"
      prompt="Here is a photo of my driving licence. Please fill this in for me."
      blurb={
        "Five pages, one question each — the shape a real service of this " +
        "kind takes. Every answer is printed on a driving licence, so a photo " +
        "of one fills the lot. Nothing here stores the picture: this form has " +
        "no upload step and the agent has no way to add one."
      }
      emptyJourney="The agent maps this out when it starts — five pages, and only the last one is yours."
    />
  );
}
