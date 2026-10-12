import { ArrowRight, Coffee, Plus } from "lucide-react";
import { Link } from "react-router-dom";

const questions = [
  { question: "What is a brew?", answer: "A brew is a personalized news digest delivered by email. You choose its topics, delivery time, and number of stories. You can create separate brews for different interests." },
  { question: "How is the news put together?", answer: "TimeBrew uses AI to find and summarize stories around your selected topics. Digests include links to the original articles so you can read the full reporting. AI summaries can make mistakes, so check the source for important details." },
  { question: "Where do I read my digest?", answer: "Your digest is delivered to the email address you sign up with. You can also open your brews and read previous briefings from your TimeBrew dashboard." },
  { question: "Is the sample showing today’s news?", answer: "No. The sample is an illustrative collection of real stories from 2024, with publication dates and links to the original announcements. It shows the reading experience, rather than a live news feed." },
];

export default function ThirdPage() {
  return (
    <>
      <section id="faq" className="tb-section tb-faq" aria-labelledby="faq-title">
        <div className="tb-container tb-faq-layout"><div><p className="tb-eyebrow">Before your first sip</p><h2 id="faq-title">A few good<br /><em>questions.</em></h2></div><div className="tb-faq-list">{questions.map(({ question, answer }) => (<details key={question}><summary>{question}<Plus size={20} aria-hidden="true" /></summary><p>{answer}</p></details>))}</div></div>
      </section>
      <section className="tb-closing" aria-labelledby="closing-title"><div className="tb-container tb-closing-inner"><div className="tb-closing-symbol" aria-hidden="true"><Coffee strokeWidth={1} /></div><p className="tb-eyebrow">Less noise. More room for life.</p><h2 id="closing-title">Your next good habit<br /><em>starts with a brew.</em></h2><Link to="/signup" className="tb-button tb-button-light">Create my brew <ArrowRight size={18} aria-hidden="true" /></Link><p className="tb-closing-note">A little perspective goes a long way.</p></div></section>
    </>
  );
}
