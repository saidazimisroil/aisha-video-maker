import { Navigate } from "react-router-dom";
import { useAuth } from "../context/AuthContext.jsx";

// Gates the main app: an unauthenticated visitor is bounced to /login. (The admin area does
// its own gating in AdminArea so it can show a separate login at /admin.)
export default function ProtectedRoute({ children }) {
  const { isAuthenticated, loading } = useAuth();
  if (loading) return null; // avoid a flash-redirect while the token is being validated
  if (!isAuthenticated) return <Navigate to="/login" replace />;
  return children;
}
