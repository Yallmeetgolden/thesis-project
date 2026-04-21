import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { useAuth } from "../context/AuthContext";

export default function Login() {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const { login, signup } = useAuth();
  const navigate = useNavigate();

  async function handleEmailLogin(e) {
    e.preventDefault();
    setError("");
    try {
      await login(email, password);
      navigate("/");
    } catch (err) {
      const msg = err?.message || String(err) || "Failed to sign in";
      if (msg === 'Failed to fetch' || msg.includes('NetworkError') || msg.includes('fetch')) {
        setError('Network error: cannot reach auth server. Is the PHP backend running?');
        return;
      }

      if (msg.toLowerCase().includes('invalid credentials') || msg.toLowerCase().includes('email') || msg.toLowerCase().includes('not found')) {
        setError('Invalid credentials or account does not exist. Use Register to create an account.');
        return;
      }

      setError(msg);
    }
  }

  async function handleRegister(e) {
    e.preventDefault();
    setError("");
    try {
      await signup(email, password);
      // auto-login after successful register
      await login(email, password);
      navigate('/');
    } catch (err) {
      const msg = err?.message || String(err) || 'Registration failed';
      setError(msg);
    }
  }

  return (
    <div className="auth-root">
      <div className="auth-box">
        <h2 className="auth-title">Sign In</h2>
        {error && <div className="auth-error">{error}</div>}
        <form onSubmit={handleEmailLogin} className="auth-form">
          <input className="auth-input" placeholder="Email" value={email} onChange={(e) => setEmail(e.target.value)} />
          <input className="auth-input" placeholder="Password" type="password" value={password} onChange={(e) => setPassword(e.target.value)} />

          <div className="auth-actions">
            <button type="submit" className="btn btn-primary">Sign In</button>
            <button type="button" className="btn btn-outline" onClick={handleRegister}>Register</button>
          </div>
        </form>
      </div>
    </div>
  );
}
