import { newsletterAddressFrom } from "./newsletterAddress";

describe("newsletterAddressFrom", () => {
  it("returns the ingest address when it looks like an email", () => {
    expect(newsletterAddressFrom({ ingest_address: "abc123@in.archie.test", id: "u1" })).toBe("abc123@in.archie.test");
  });

  it("returns null for a missing, non-string or malformed address and for non-objects", () => {
    expect(newsletterAddressFrom({})).toBeNull();
    expect(newsletterAddressFrom({ ingest_address: null })).toBeNull();
    expect(newsletterAddressFrom({ ingest_address: 5 })).toBeNull();
    expect(newsletterAddressFrom({ ingest_address: "no-at-sign" })).toBeNull();
    expect(newsletterAddressFrom(null)).toBeNull();
    expect(newsletterAddressFrom("x@y")).toBeNull();
  });
});
