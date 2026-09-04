export function AccessPage({
  title,
  message,
}: {
  title: string;
  message: string;
}) {
  return (
    <div className="page">
      <h1 className="page-title">{title}</h1>
      <div className="card">
        <p>{message}</p>
        <p className="muted">Open this Mini App from the Telegram bot as an authorized user.</p>
      </div>
    </div>
  );
}
