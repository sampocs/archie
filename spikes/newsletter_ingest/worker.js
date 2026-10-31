// Saves every email to the domain untouched, so the parsing can be tested offline on real newsletters
export default {
  async email(message, env) {
    const raw = await new Response(message.raw).arrayBuffer();
    const key = `${new Date().toISOString()}_${message.to}`;
    await env.INBOX.put(key, raw, {
      metadata: { from: message.from, to: message.to, subject: message.headers.get("subject") ?? "" },
    });
  },
};
