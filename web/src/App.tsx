import { Navigate, Route, Routes } from "react-router";
import { useMe } from "./lib/hooks";
import { ApiError } from "./lib/api";
import LoginPage from "./pages/LoginPage";
import DeskPage from "./pages/DeskPage";
import JobsPage from "./pages/JobsPage";

export default function App() {
  const me = useMe();
  if (me.isPending) return <p className="boot muted">Opening the order desk…</p>;
  const signedIn = me.isSuccess;
  if (me.isError && !(me.error instanceof ApiError && me.error.status === 401)) {
    return <p className="boot error-text">Can't reach the server: {me.error.message}</p>;
  }
  return (
    <Routes>
      <Route path="/login" element={signedIn ? <Navigate to="/" replace /> : <LoginPage />} />
      <Route path="/jobs" element={signedIn ? <JobsPage me={me.data} /> : <Navigate to="/login" replace />} />
      <Route path="/orders/:id" element={signedIn ? <DeskPage me={me.data} /> : <Navigate to="/login" replace />} />
      <Route path="*" element={signedIn ? <DeskPage me={me.data} /> : <Navigate to="/login" replace />} />
    </Routes>
  );
}
