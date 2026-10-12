import { ArrowDown, ArrowRight, ArrowUpRight, Check, Coffee, Mail } from "lucide-react";
import { Link } from "react-router-dom";
import { sampleStories } from "./sampleStories";

interface FirstPageProps { onOpenSample: () => void }

export default function FirstPage({ onOpenSample }: FirstPageProps) {
  return (
    <section className="tb-hero" aria-labelledby="landing-title">
      <div className="tb-container tb-hero-grid">
        <div className="tb-hero-copy">
          <p className="tb-eyebrow"><span className="tb-status-dot" /> Your daily news ritual</p>
          <h1 id="landing-title">A little more<br />perspective.<br /><em>A lot less scroll.</em></h1>
          <p className="tb-hero-description">The stories you care about, brewed into a personal digest. Pick your topics, choose your time, and make room for the rest of your day.</p>
          <div className="tb-hero-actions">
            <Link to="/signup" className="tb-button tb-button-primary">Create my brew <ArrowRight size={18} aria-hidden="true" /></Link>
            <button className="tb-button tb-button-outline" onClick={onOpenSample}>Read a sample <ArrowUpRight size={18} aria-hidden="true" /></button>
          </div>
          <p className="tb-hero-note"><Mail size={15} aria-hidden="true" /> Delivered to your inbox. Made for your routine.</p>
          <a className="tb-explore-link" href="#how-it-works">A better way to catch up <ArrowDown size={15} aria-hidden="true" /></a>
        </div>

        <div className="tb-hero-preview" id="sample">
          <div className="tb-preview-label"><span className="tb-small-rule" /> A peek inside your next ritual</div>
          <article className="tb-newspaper" aria-label="Historical sample digest preview">
            <div className="tb-newspaper-masthead"><span>TimeBrew<span className="tb-masthead-period">.</span></span><Coffee size={28} strokeWidth={1.4} aria-hidden="true" /></div>
            <div className="tb-edition-line"><span>The curiosity edit</span><span>2024 archive sample</span></div>
            <div className="tb-newspaper-welcome"><h2>Hello, curious mind.</h2><p>Three stories worth a moment of your day.</p></div>
            <article className="tb-preview-lead">
              <div className="tb-story-eyebrow"><span>01 / Space</span><span>NASA · Oct 14, 2024</span></div>
              <h3>{sampleStories[0].title}</h3>
              <p>Europa Clipper set off for Jupiter’s icy moon to explore whether its hidden ocean could support life. A long journey, with a very human question at its heart.</p>
              <a href={sampleStories[0].url} target="_blank" rel="noopener noreferrer" className="tb-source-link">Read the original <ArrowUpRight size={14} aria-hidden="true" /><span className="sr-only"> at NASA (opens in a new tab)</span></a>
            </article>
            {sampleStories.slice(1).map((story, index) => (
              <div className="tb-preview-short" key={story.url}>
                <span className="tb-story-number">0{index + 2}</span>
                <div><span className="tb-short-topic">{story.topic} · {story.date}</span><h3>{story.title}</h3></div>
              </div>
            ))}
            <button className="tb-preview-read" onClick={onOpenSample}>Read the full sample <ArrowRight size={17} aria-hidden="true" /></button>
          </article>
          <div className="tb-preview-caption"><Check size={14} aria-hidden="true" /><span>Real stories. Original sources. A historical example.</span></div>
        </div>
      </div>
      <div className="tb-container tb-hero-bottom"><span>Your interests.</span><span>Your inbox.</span><span>Your kind of informed.</span><Coffee size={19} aria-hidden="true" /></div>
    </section>
  );
}
