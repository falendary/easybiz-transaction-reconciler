import { NavLink } from "react-router-dom";

export default function Nav() {
  return (
    <nav>
      <span className="brand">EasyBiz Reconciler</span>
      <NavLink to="/" end className={({ isActive }) => isActive ? "active" : ""}>
        Ingest
      </NavLink>
      <NavLink to="/dashboard" className={({ isActive }) => isActive ? "active" : ""}>
        Dashboard
      </NavLink>
    </nav>
  );
}
