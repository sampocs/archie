import {
  confirmExplanation,
  confirmFrom,
  confirmHeadline,
  confirmPrompt,
  confirmToast,
  isGmailForwarding,
  type ConfirmationSource,
} from "./confirmations";

const tldr: ConfirmationSource = {
  confirmUrl: "https://example.com/confirm-signup",
  sender: "TLDR",
  title: "TLDR - Confirm your signup",
};
const noSender: ConfirmationSource = { ...tldr, sender: null };
const gmail: ConfirmationSource = {
  confirmUrl: "https://mail-settings.google.com/mail/vf-example",
  sender: "Gmail Team",
  title: "(Gmail Forwarding Confirmation - Receive Mail from owner@example.com",
};

describe("confirmations", () => {
  it("tells Gmail forwarding by its link's host, not by the sender or title", () => {
    expect(isGmailForwarding(gmail)).toBe(true);
    expect(isGmailForwarding(tldr)).toBe(false);
    expect(isGmailForwarding({ ...tldr, title: gmail.title, sender: "Gmail Team" })).toBe(false);
    expect(isGmailForwarding({ ...tldr, confirmUrl: "https://mail-settings.google.com.evil.test/x" })).toBe(false);
  });

  it("words a newsletter signup around its sender", () => {
    expect(confirmHeadline(tldr)).toBe("Confirm your TLDR signup");
    expect(confirmFrom(tldr)).toBe("TLDR");
    expect(confirmToast(tldr)).toBe("TLDR signup confirmed");
    expect(confirmPrompt(tldr)).toBe("This email asks you to confirm your TLDR signup.");
    expect(confirmExplanation(tldr)).toBe(
      "Confirm opens the newsletter's link. Once you're done, Archie deletes this email, and TLDR's issues start arriving as normal newsletters.",
    );
  });

  it("falls back to 'newsletter' when the sender is missing or blank", () => {
    for (const source of [noSender, { ...tldr, sender: "  " }]) {
      expect(confirmHeadline(source)).toBe("Confirm your newsletter signup");
      expect(confirmFrom(source)).toBe("Newsletter");
      expect(confirmToast(source)).toBe("Newsletter signup confirmed");
      expect(confirmPrompt(source)).toBe("This email asks you to confirm your newsletter signup.");
      expect(confirmExplanation(source)).toContain("and its issues start arriving");
    }
  });

  it("words Gmail forwarding without a sender, taking the address from the subject", () => {
    expect(confirmHeadline(gmail)).toBe("Confirm Gmail forwarding");
    expect(confirmFrom(gmail)).toBe("From owner@example.com");
    expect(confirmToast(gmail)).toBe("Gmail forwarding confirmed");
    expect(confirmPrompt(gmail)).toBe("This email asks you to confirm Gmail forwarding.");
    expect(confirmExplanation(gmail)).toBe(
      "Confirm opens Google's link. Once you're done, Archie deletes this email, and forwarded mail starts arriving as normal newsletters.",
    );
  });

  it("falls back to the sender when the Gmail subject has no address", () => {
    expect(confirmFrom({ ...gmail, title: "Gmail Forwarding Confirmation" })).toBe("From Gmail Team");
    expect(confirmFrom({ ...gmail, title: null, sender: null })).toBe("From Gmail");
  });
});
