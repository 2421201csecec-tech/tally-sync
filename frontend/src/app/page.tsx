import Link from "next/link";

export default function Home() {
  return (
    <main className="shell hero">
      <section className="hero-copy">
        <p className="eyebrow">TALLY SYNC</p>
        <h1>Connect Tally to the cloud, securely.</h1>
        <p className="lead">
          Install a small agent on the PC where Tally runs. Approve it here,
          choose the companies it can sync, and keep control of your data.
        </p>
        <div className="actions">
          <Link className="button" href="/signup">Create account</Link>
          <Link className="button secondary" href="/login">Log in</Link>
        </div>
      </section>
      <section className="feature-grid">
        <div className="panel"><strong>Private by design</strong><span>Your agent only syncs companies you explicitly enable.</span></div>
        <div className="panel"><strong>Read-only access</strong><span>Tally Sync reads ledgers, stock, and vouchers without changing Tally.</span></div>
        <div className="panel"><strong>Revoke anytime</strong><span>Disconnect an agent from your dashboard whenever you need.</span></div>
      </section>
    </main>
  );
}
