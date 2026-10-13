import { Coffee } from "lucide-react";
import { Link } from "react-router-dom";

export default function Footer() {
  return (
    <footer className="tb-footer">
      <div className="tb-container tb-footer-top"><div><Link className="tb-brand" to="/" aria-label="TimeBrew home"><Coffee size={24} strokeWidth={1.6} aria-hidden="true" /><span>TimeBrew<span className="tb-brand-dot">.</span></span></Link><p>A little perspective. Every day.</p></div><nav aria-label="Footer navigation"><Link to="/#features">Why TimeBrew</Link><Link to="/#how-it-works">How it works</Link><Link to="/#faq">Questions</Link><Link to="/signin">Log in</Link></nav></div>
      <div className="tb-container tb-footer-bottom"><p>© {new Date().getFullYear()} TimeBrew</p><p>Brewed for curious minds.</p></div>
    </footer>
  );
}
