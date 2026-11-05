import { primerButtonKind } from "./PrimerButton";

describe("primerButtonKind", () => {
  it("opens an existing primer whatever the pipeline is doing", () => {
    expect(primerButtonKind({ kind: "article", processing: "failed" }, 900)).toBe("open");
  });

  it("shows the primer as being written while the pipeline runs", () => {
    expect(primerButtonKind({ kind: "article", processing: "processing" }, null)).toBe("writing");
    expect(primerButtonKind({ kind: "newsletter", processing: "pending" }, null)).toBe("writing");
  });

  it("offers to create one only for a ready newsletter", () => {
    expect(primerButtonKind({ kind: "newsletter", processing: "ready" }, null)).toBe("create");
    expect(primerButtonKind({ kind: "article", processing: "ready" }, null)).toBeNull();
  });

  it("shows no primer button for a failed item, which has nothing being written", () => {
    expect(primerButtonKind({ kind: "article", processing: "failed" }, null)).toBeNull();
    expect(primerButtonKind({ kind: "newsletter", processing: "failed" }, null)).toBeNull();
  });
});
