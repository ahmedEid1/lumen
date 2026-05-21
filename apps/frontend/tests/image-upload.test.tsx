import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { ImageUpload } from "@/components/shared/image-upload";
import * as apiClient from "@/lib/api/client";

// `vi.mock()` is hoisted to the top of the module by the
// vitest transformer, so references inside the factory are
// evaluated BEFORE module-level `const`s exist. Wrap the toast
// spies in `vi.hoisted()` so they're available when the factory
// runs — vitest's documented escape hatch for this exact pattern.
const { toastError, toastSuccess } = vi.hoisted(() => ({
  toastError: vi.fn(),
  toastSuccess: vi.fn(),
}));
vi.mock("sonner", () => ({ toast: { error: toastError, success: toastSuccess } }));

// presign switched from PUT to POST so S3 enforces the
// content-length-range. Response shape is now {url, fields, max_bytes}.
const PRESIGN = {
  method: "POST" as const,
  url: "https://s3.test/lumen-assets",
  fields: {
    "Content-Type": "image/png",
    key: "avatar/u/2026/05/21/abc/cat.png",
    policy: "eyJleHBpcmF0aW9uIjoiZmFrZSJ9",
    "x-amz-signature": "deadbeef",
  },
  key: "avatar/u/2026/05/21/abc/cat.png",
  expires_in: 900,
  public_url: "https://s3.test/lumen-assets/avatar/u/2026/05/21/abc/cat.png",
  max_bytes: 5 * 1024 * 1024,
};

function pngFile(size = 1024, name = "cat.png") {
  // happy-dom's File constructor wants an array of BlobParts
  const bytes = new Uint8Array(size);
  return new File([bytes], name, { type: "image/png" });
}

function pickFile(file: File) {
  const input = document.querySelector('input[type="file"]') as HTMLInputElement;
  expect(input).toBeTruthy();
  return userEvent.setup().upload(input, file);
}

describe("ImageUpload", () => {
  let apiSpy: ReturnType<typeof vi.spyOn>;
  let fetchMock: ReturnType<typeof vi.fn>;
  let originalFetch: typeof globalThis.fetch;

  beforeEach(() => {
    apiSpy = vi.spyOn(apiClient, "api");
    originalFetch = globalThis.fetch;
    fetchMock = vi.fn();
    // @ts-expect-error — install the test double
    globalThis.fetch = fetchMock;
    toastError.mockReset();
    toastSuccess.mockReset();
  });

  afterEach(() => {
    vi.restoreAllMocks();
    globalThis.fetch = originalFetch;
  });

  it("renders the 'none' placeholder when no value is set", () => {
    render(<ImageUpload kind="avatar" value={null} onChange={vi.fn()} label="Avatar" />);
    expect(screen.getByText("none")).toBeInTheDocument();
    expect(screen.getByText("Avatar")).toBeInTheDocument();
    expect(screen.getByText(/choose file/i)).toBeInTheDocument();
  });

  it("renders the preview img when a value is provided", () => {
    render(<ImageUpload kind="avatar" value="https://x.test/a.png" onChange={vi.fn()} />);
    const img = document.querySelector('img[src="https://x.test/a.png"]');
    expect(img).not.toBeNull();
    expect(screen.getByText(/remove/i)).toBeInTheDocument();
  });

  it("rejects files larger than the per-kind cap without calling the API", async () => {
    const onChange = vi.fn();
    render(<ImageUpload kind="avatar" value={null} onChange={onChange} />);

    // Avatar cap is 5 MiB; ship 6 MiB
    await pickFile(pngFile(6 * 1024 * 1024));

    expect(toastError).toHaveBeenCalledWith(expect.stringContaining("too large"));
    expect(apiSpy).not.toHaveBeenCalled();
    expect(fetchMock).not.toHaveBeenCalled();
    expect(onChange).not.toHaveBeenCalled();
  });

  it("signs, POSTs multipart form-data with all fields + file, and calls onChange on success", async () => {
    apiSpy.mockResolvedValueOnce(PRESIGN as never);
    fetchMock.mockResolvedValueOnce(new Response(null, { status: 204 }) as never);
    const onChange = vi.fn();

    render(<ImageUpload kind="avatar" value={null} onChange={onChange} />);
    await pickFile(pngFile(1024));

    await waitFor(() => expect(onChange).toHaveBeenCalledWith(PRESIGN.public_url));
    expect(apiSpy).toHaveBeenCalledWith(
      "/api/v1/uploads/sign",
      expect.objectContaining({
        method: "POST",
        body: expect.objectContaining({
          filename: "cat.png",
          content_type: "image/png",
          kind: "avatar",
          size_bytes: 1024,
        }),
      }),
    );
    // S3 upload is now multipart POST with all signed fields + the file.
    const [calledUrl, calledInit] = fetchMock.mock.calls[0];
    expect(calledUrl).toBe(PRESIGN.url);
    expect(calledInit.method).toBe("POST");
    expect(calledInit.body).toBeInstanceOf(FormData);
    const fd = calledInit.body as FormData;
    // Every signed field must be present.
    for (const [k, v] of Object.entries(PRESIGN.fields)) {
      expect(fd.get(k)).toBe(v);
    }
    // And the file must be last.
    expect(fd.get("file")).toBeInstanceOf(File);
    expect(toastSuccess).toHaveBeenCalledWith("Uploaded");
  });

  it("surfaces a friendly toast when S3 returns 403 EntityTooLarge", async () => {
    apiSpy.mockResolvedValueOnce(PRESIGN as never);
    fetchMock.mockResolvedValueOnce(new Response(null, { status: 403 }) as never);
    const onChange = vi.fn();

    render(<ImageUpload kind="avatar" value={null} onChange={onChange} />);
    await pickFile(pngFile(1024));

    await waitFor(() => expect(toastError).toHaveBeenCalled());
    expect(toastError.mock.calls[0][0]).toMatch(/exceeds the 5 MB limit/i);
    expect(onChange).not.toHaveBeenCalled();
  });

  it("surfaces a generic toast on other S3 failures", async () => {
    apiSpy.mockResolvedValueOnce(PRESIGN as never);
    fetchMock.mockResolvedValueOnce(new Response(null, { status: 500 }) as never);
    const onChange = vi.fn();

    render(<ImageUpload kind="avatar" value={null} onChange={onChange} />);
    await pickFile(pngFile(1024));

    await waitFor(() => expect(toastError).toHaveBeenCalled());
    expect(onChange).not.toHaveBeenCalled();
  });

  it("Remove button clears the value via onChange(null)", async () => {
    const onChange = vi.fn();
    render(<ImageUpload kind="avatar" value="https://x.test/a.png" onChange={onChange} />);

    await userEvent.setup().click(screen.getByRole("button", { name: /remove/i }));
    expect(onChange).toHaveBeenCalledWith(null);
  });
});
