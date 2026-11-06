import Link from "next/link";
import Header from "../components/Header";
import AuthForm from "../components/AuthForm";

export default function SignupPage() {
  return <><Header /><main className="auth card"><h1>Create your account</h1><AuthForm signup /><p className="muted">Already registered? <Link href="/login">Log in</Link>.</p></main></>;
}
