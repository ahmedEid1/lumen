import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { ImageUpload } from "@/components/shared/image-upload";
import * as apiClient from "@/lib/api/client";

const toastError = vi.fn();
const toastSuccess = vi.fn();
vi.mock("sonner", () => ({ toast: { error: toastError, success: toastSuccess } }));

const PRESIGN = {
  method: "PUT" as const,
  url: "https://s3.test/upload?sig=x",
  key: "avatar/u/2026/05/21/abc/cat.png",
  headers: { "Content-Type": "image/png" },
  expires_in: 900,
  public_url: "https://s3.test/lumen-assets/avatar/u/2026/05/21/abc/cat.png",
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

  it("signs, PUTs, and calls onChange with the public URL on success", async () => {
    apiSpy.mockResolvedValueOnce(PRESIGN as never);
    fetchMock.mockResolvedValueOnce(new Response(null, { status: 200 }) as never);
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
    expect(fetchMock).toHaveBeenCalledWith(
      PRESIGN.url,
      expect.objectContaining({ method: "PUT", headers: { "Content-Type": "image/png" } }),
    );
    expect(toastSuccess).toHaveBeenCalledWith("Uploaded");
  });

  it("surfaces a toast error when the S3 PUT fails", async () => {
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
