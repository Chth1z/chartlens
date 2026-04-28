import { Navigate, Route, Routes } from "react-router-dom";
import { ChartLensApp } from "./features/app/ChartLensApp";

export function App() {
  return (
    <Routes>
      <Route path="/" element={<Navigate to="/cases" replace />} />
      <Route path="/cases" element={<ChartLensApp />} />
      <Route path="/cases/:caseId" element={<ChartLensApp />} />
      <Route path="/cases/:caseId/review" element={<ChartLensApp />} />
      <Route path="/settings" element={<ChartLensApp />} />
      <Route path="/diagnostics" element={<ChartLensApp />} />
      <Route path="/evals" element={<ChartLensApp />} />
      <Route path="/auth/complete" element={<ChartLensApp />} />
      <Route path="*" element={<Navigate to="/cases" replace />} />
    </Routes>
  );
}
