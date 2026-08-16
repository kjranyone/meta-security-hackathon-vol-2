import { useEffect, useRef } from "react";
import { renderChart } from "../lib/renderChart";

export default function PriceChart({ ticks }) {
  const cvRef = useRef(null);

  useEffect(() => {
    const cv = cvRef.current;
    if (!cv) return;
    const fit = () => {
      if (!cv.clientWidth || !cv.clientHeight) return;
      const w = cv.clientWidth * 2, h = cv.clientHeight * 2;   // 2x backing for crisp lines
      if (cv.width !== w || cv.height !== h) { cv.width = w; cv.height = h; }
      renderChart(cv.getContext("2d"), cv, ticks);
    };
    const ro = new ResizeObserver(fit);
    ro.observe(cv);
    fit();
    return () => ro.disconnect();
  }, [ticks]);

  return <canvas ref={cvRef} className="chart" />;
}
