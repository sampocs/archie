// Forwards every email to Archie's API, and keeps the raw message in KV as a debugging record.
export default {
  async email(message, env) {
    const raw = await new Response(message.raw).arrayBuffer();
    await env.INBOX.put(`${new Date().toISOString()}_${message.to}`, raw, {
      metadata: { from: message.from, to: message.to, subject: message.headers.get("subject") ?? "" },
    });

    const response = await fetch(`${env.API_URL}/ingest/email`, {
      method: "POST",
      headers: {
        "content-type": "message/rfc822",
        "x-ingest-secret": env.INGEST_SECRET,
        "x-ingest-to": message.to,
        "x-ingest-from": message.from,
      },
      body: raw,
    });
    // Throwing makes Cloudflare retry or bounce, so a failed delivery is never silently lost.
    if (!response.ok) throw new Error(`Archie ingest answered ${response.status}`);
  },
};
