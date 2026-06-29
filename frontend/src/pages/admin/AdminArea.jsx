import { Link } from "react-router-dom";
import { useAuth } from "../../context/AuthContext.jsx";
import AdminLogin from "./AdminLogin.jsx";
import AdminUsers from "./AdminUsers.jsx";

// Gate for /admin: signed-out → admin login; signed-in non-admin → not-authorized; otherwise
// the user-management console. Keeping the login here (rather than redirecting to /login) is
// what makes the admin entrance a separate surface a normal-user session can't cross into.
export default function AdminArea() {
  const { loading, isAuthenticated, isAdmin, user, logout } = useAuth();

  if (loading) return null;
  if (!isAuthenticated) return <AdminLogin />;
  if (!isAdmin) {
    return (
      <div className="auth-wrap">
        <div className="card auth-card center">
          <h1>Not authorized</h1>
          <p className="page-sub">
            Your account (<strong>{user.username}</strong>) doesn't have admin access.
          </p>
          <div className="row" style={{ justifyContent: "center" }}>
            <Link className="btn" to="/">Go to app</Link>
            <button className="btn" onClick={logout}>Log out</button>
          </div>
        </div>
      </div>
    );
  }
  return <AdminUsers />;
}
