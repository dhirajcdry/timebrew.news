import { useEffect, useRef } from "react";
import { Link } from "react-router-dom";
import { ArrowRight, ArrowUpRight, Coffee, X } from "lucide-react";
import { sampleStories } from "./sampleStories";

interface SampleDigestProps {
  isOpen: boolean;
  onClose: () => void;
}

export default function SampleDigest({ isOpen, onClose }: SampleDigestProps) {
  const dialogRef = useRef<HTMLDialogElement>(null);
  const closeRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    const dialog = dialogRef.current;
    if (!isOpen || !dialog) return;

    const opener = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    const previousOverflow = document.body.style.overflow;
    // The native modal dialog provides focus containment and makes the page inert.
    if (!dialog.open) dialog.showModal();
    document.body.style.overflow = "hidden";
    closeRef.current?.focus();

    return () => {
      dialog.close();
      document.body.style.overflow = previousOverflow;
      if (opener?.isConnected) opener.focus({ preventScroll: true });
    };
  }, [isOpen]);

  return (
    <dialog
      ref={dialogRef}
      className="tb-sample-dialog"
      aria-labelledby="sample-digest-title"
      aria-describedby="sample-digest-description"
      onCancel={(event) => { event.preventDefault(); onClose(); }}
      onClick={(event) => {
        const bounds = event.currentTarget.getBoundingClientRect();
        if (event.target === event.currentTarget && (
          event.clientX < bounds.left || event.clientX > bounds.right ||
          event.clientY < bounds.top || event.clientY > bounds.bottom
        )) onClose();
      }}
    >
      <div className="tb-dialog-toolbar">
        <span><Coffee size={18} aria-hidden="true" /> A taste of TimeBrew</span>
        <button ref={closeRef} className="tb-icon-button" onClick={onClose} aria-label="Close sample digest"><X size={22} /></button>
      </div>
      <div className="tb-dialog-body">
        <div className="tb-edition-line"><span>The curiosity edit</span><span>Archive collection</span></div>
        <h2 id="sample-digest-title">Good stories.<br />A little perspective.</h2>
        <p id="sample-digest-description" className="tb-sample-disclaimer">Illustrative sample using three real stories from 2024. This is a historical example, not today’s news or a live generated digest.</p>
        <p className="tb-digest-intro">From an ocean beneath the ice to the proteins inside our cells, there’s plenty to be curious about. Here’s the short version.</p>
        {sampleStories.map((story, index) => (
          <article className="tb-sample-story" key={story.url}>
            <div className="tb-story-eyebrow"><span>0{index + 1} / {story.topic}</span><time dateTime={story.dateTime}>{story.date}</time></div>
            <h3>{story.title}</h3>
            <p>{story.summary}</p>
            <p className="tb-takeaway"><strong>The takeaway</strong> {story.takeaway}</p>
            <a href={story.url} target="_blank" rel="noopener noreferrer" className="tb-source-link">Read the original at {story.source}<ArrowUpRight size={15} aria-hidden="true" /><span className="sr-only"> (opens in a new tab)</span></a>
          </article>
        ))}
        <div className="tb-digest-signoff"><Coffee size={26} aria-hidden="true" /><p>You’re all caught up.<br /><span>Go enjoy the rest of your day.</span></p></div>
        <Link to="/signup" className="tb-button tb-button-primary" onClick={onClose}>Create your own brew <ArrowRight size={17} aria-hidden="true" /></Link>
      </div>
    </dialog>
  );
}
