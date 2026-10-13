import { ArrowRight, Check, Clock3, Mail, SlidersHorizontal } from "lucide-react";
import { Link } from "react-router-dom";

const steps = [
  { number: "01", title: "Pick your interests.", description: "Technology, science, business, or something else. Give each brew a name and choose what belongs in it.", icon: SlidersHorizontal },
  { number: "02", title: "Set your rhythm.", description: "Choose a delivery time and the number of stories. A quick morning catch-up or a little more to read later.", icon: Clock3 },
  { number: "03", title: "Open. Read. Carry on.", description: "Your AI-curated digest lands in your inbox. Get the essentials, then follow the source when you want to go deeper.", icon: Mail },
];

export default function SecondPage() {
  return (
    <>
      <section id="features" className="tb-section tb-features" aria-labelledby="features-title">
        <div className="tb-container">
          <div className="tb-section-heading"><p className="tb-eyebrow">A healthier news habit</p><h2 id="features-title">Stay curious.<br /><em>Keep your headspace.</em></h2><p>The world has plenty to say. Your daily reading should still feel like it belongs to you.</p></div>
          <div className="tb-feature-grid">
            <article className="tb-feature-card">
              <div className="tb-feature-art tb-topic-art" aria-hidden="true"><span>Space</span><span className="tb-topic-selected"><Check size={13} /> Technology</span><span>Business</span><span className="tb-topic-selected"><Check size={13} /> Science</span><span>Design</span><span>Climate</span></div>
              <span className="tb-feature-kicker">Your interests, in focus</span><h3>A brew with your name on it.</h3><p>Choose the topics you want to follow. Keep different interests in their own brews.</p>
            </article>
            <article className="tb-feature-card">
              <div className="tb-feature-art tb-clock-art" aria-hidden="true"><div className="tb-clock-face"><span className="tb-clock-hour" /><span className="tb-clock-minute" /><span className="tb-clock-dot" /></div><div><strong>07:30<span> AM</span></strong><span>Your morning moment</span></div></div>
              <span className="tb-feature-kicker">A rhythm that feels right</span><h3>News on your clock.</h3><p>Set a delivery time for each brew. Make the news part of your routine, on your terms.</p>
            </article>
            <article className="tb-feature-card">
              <div className="tb-feature-art tb-length-art" aria-hidden="true"><div className="tb-mini-story"><span>01</span><div><strong>The story, in a nutshell.</strong><span>The context you came for.</span></div><Check size={16} /></div><div className="tb-mini-story"><span>02</span><div><strong>A little more perspective.</strong><span>A source to explore further.</span></div><Check size={16} /></div></div>
              <span className="tb-feature-kicker">An ending you can reach</span><h3>A digest. Then you’re done.</h3><p>Choose how many stories to receive. Read a concise summary, with a link to the original.</p>
            </article>
          </div>
        </div>
      </section>
      <section id="how-it-works" className="tb-section tb-how" aria-labelledby="how-title">
        <div className="tb-container tb-how-layout">
          <div className="tb-how-intro"><p className="tb-eyebrow">Simple by design</p><h2 id="how-title">Make it<br /><em>your daily brew.</em></h2><p>A few choices now.<br />A more intentional way to stay informed.</p><Link to="/signup" className="tb-text-link">Find your rhythm <ArrowRight size={18} aria-hidden="true" /></Link></div>
          <div className="tb-step-list">{steps.map(({ number, title, description, icon: Icon }) => (<article className="tb-step" key={number}><span className="tb-step-number">{number}</span><div><h3>{title}</h3><p>{description}</p></div><Icon className="tb-step-icon" size={25} strokeWidth={1.4} aria-hidden="true" /></article>))}</div>
        </div>
      </section>
    </>
  );
}
