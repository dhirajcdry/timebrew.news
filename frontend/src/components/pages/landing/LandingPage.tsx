import { useCallback, useState } from "react";
import FirstPage from "./FirstPage";
import SecondPage from "./SecondPage";
import ThirdPage from "./ThirdPage";
import SampleDigest from "./SampleDigest";

export default function LandingPage() {
  const [sampleOpen, setSampleOpen] = useState(false);
  const closeSample = useCallback(() => setSampleOpen(false), []);

  return (
    <div className="tb-landing" id="landing-content" tabIndex={-1}>
      <FirstPage onOpenSample={() => setSampleOpen(true)} />
      <SecondPage />
      <ThirdPage />
      <SampleDigest isOpen={sampleOpen} onClose={closeSample} />
    </div>
  );
}
