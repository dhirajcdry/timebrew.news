import { useEffect, useRef, useState } from "react";
import { ArrowRight, Coffee, LogOut, Menu, X } from "lucide-react";
import { Link, useLocation } from "react-router-dom";
import { useAuth } from "@/contexts/AuthContext";
import ThemeToggle from "./ThemeToggle";

const sectionLinks = [
  { to: "/#features", label: "Why TimeBrew" },
  { to: "/#how-it-works", label: "How it works" },
  { to: "/#faq", label: "Questions" },
];

export default function Navbar() {
  const { isAuthenticated, user, logout } = useAuth();
  const location = useLocation();
  const [menuOpen, setMenuOpen] = useState(false);
  const headerRef = useRef<HTMLElement>(null);
  const menuButtonRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    setMenuOpen(false);
    if (location.pathname !== "/" || !location.hash) return;
    const frame = requestAnimationFrame(() => {
      const section = document.getElementById(location.hash.slice(1));
      if (section) {
        section.scrollIntoView({ behavior: window.matchMedia("(prefers-reduced-motion: reduce)").matches ? "instant" : "smooth" });
        // Make cross-route section navigation usable with a keyboard, too.
        section.setAttribute("tabindex", "-1");
        section.focus({ preventScroll: true });
      }
    });
    return () => cancelAnimationFrame(frame);
  }, [location.pathname, location.hash, location.key]);

  useEffect(() => {
    if (!menuOpen) return;
    const onPointerDown = (event: PointerEvent) => {
      if (!headerRef.current?.contains(event.target as Node)) setMenuOpen(false);
    };
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") { setMenuOpen(false); menuButtonRef.current?.focus(); }
    };
    const onResize = () => { if (window.innerWidth >= 900) setMenuOpen(false); };
    document.addEventListener("pointerdown", onPointerDown);
    document.addEventListener("keydown", onKeyDown);
    window.addEventListener("resize", onResize);
    return () => {
      document.removeEventListener("pointerdown", onPointerDown);
      document.removeEventListener("keydown", onKeyDown);
      window.removeEventListener("resize", onResize);
    };
  }, [menuOpen]);

  const closeMenu = () => setMenuOpen(false);
  const navigation = isAuthenticated ? (
    <>
      <Link to="/dashboard" onClick={closeMenu}>My brews</Link>
      <span className="tb-nav-greeting">Hi, {user?.firstName || "there"}</span>
      <button className="tb-nav-logout" onClick={() => { logout(); closeMenu(); }}><LogOut size={16} aria-hidden="true" /> Log out</button>
    </>
  ) : (
    <>
      {sectionLinks.map(({ to, label }) => <Link key={to} to={to} onClick={closeMenu}>{label}</Link>)}
      <Link className="tb-nav-signin" to="/signin" onClick={closeMenu}>Log in</Link>
      <Link className="tb-button tb-button-primary tb-nav-cta" to="/signup" onClick={closeMenu}>Create my brew <ArrowRight size={16} aria-hidden="true" /></Link>
    </>
  );

  return (
    <header className="tb-site-header" ref={headerRef}>
      {location.pathname === "/" && <a href="#landing-content" className="tb-skip-link">Skip to content</a>}
      <div className="tb-container tb-nav-bar">
        <Link className="tb-brand" to="/" aria-label="TimeBrew home" onClick={() => { closeMenu(); if (location.pathname === "/") window.scrollTo({ top: 0 }); }}><span className="tb-brand-icon"><Coffee size={24} strokeWidth={1.7} aria-hidden="true" /></span><span>TimeBrew<span className="tb-brand-dot">.</span></span></Link>
        <nav className="tb-desktop-nav" aria-label="Main navigation">{navigation}<ThemeToggle variant="minimal" className="tb-theme-toggle" /></nav>
        <div className="tb-mobile-actions"><ThemeToggle variant="minimal" className="tb-theme-toggle" /><button ref={menuButtonRef} className="tb-icon-button" aria-label={menuOpen ? "Close navigation" : "Open navigation"} aria-expanded={menuOpen} aria-controls="mobile-navigation" onClick={() => setMenuOpen(!menuOpen)}>{menuOpen ? <X size={23} aria-hidden="true" /> : <Menu size={23} aria-hidden="true" />}</button></div>
      </div>
      <nav id="mobile-navigation" className="tb-mobile-nav" aria-label="Mobile navigation" hidden={!menuOpen}>{navigation}</nav>
    </header>
  );
}
