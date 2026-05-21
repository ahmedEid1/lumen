import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { ChatRoom } from "@/components/chat/chat-room";

/**
 * Minimal WebSocket double — captures sent frames, exposes hooks to simulate
 * server-pushed messages, and lets the test trigger open/close lifecycle.
 */
class MockWebSocket {
  static CONNECTING = 0;
  static OPEN = 1;
  static CLOSING = 2;
  static CLOSED = 3;

  static instances: MockWebSocket[] = [];

  readyState: number = MockWebSocket.CONNECTING;
  sent: string[] = [];
  onopen: ((this: WebSocket, ev: Event) => any) | null = null;
  onclose: ((this: WebSocket, ev: CloseEvent) => any) | null = null;
  onmessage: ((this: WebSocket, ev: MessageEvent) => any) | null = null;
  onerror: ((this: WebSocket, ev: Event) => any) | null = null;
  url: string;

  constructor(url: string) {
    this.url = url;
    MockWebSocket.instances.push(this);
  }

  send(data: string) {
    this.sent.push(data);
  }

  close(code = 1000) {
    this.readyState = MockWebSocket.CLOSED;
    this.onclose?.call(this as unknown as WebSocket, { code, reason: "" } as CloseEvent);
  }

  /** Pretend the server accepted the connection. */
  simulateOpen() {
    this.readyState = MockWebSocket.OPEN;
    this.onopen?.call(this as unknown as WebSocket, new Event("open"));
  }

  /** Pretend the server pushed an arbitrary JSON frame. */
  push(frame: unknown) {
    this.onmessage?.call(
      this as unknown as WebSocket,
      { data: JSON.stringify(frame) } as MessageEvent,
    );
  }
}

const messageFrame = (id: string, body: string) => ({
  type: "message" as const,
  data: {
    id,
    course_id: "c1",
    body,
    created_at: new Date().toISOString(),
    author: { id: "u1", full_name: "Lina", avatar_url: null, bio: null, role: "student" },
  },
});

describe("ChatRoom", () => {
  let originalWebSocket: typeof globalThis.WebSocket;

  beforeEach(() => {
    MockWebSocket.instances = [];
    originalWebSocket = globalThis.WebSocket;
    // @ts-expect-error — assigning the test double
    globalThis.WebSocket = MockWebSocket;
  });

  afterEach(() => {
    globalThis.WebSocket = originalWebSocket;
    vi.restoreAllMocks();
  });

  it("renders the placeholder + Connecting pill before the socket opens", () => {
    render(<ChatRoom courseId="c1" token="t" />);
    expect(screen.getByText(/no messages yet/i)).toBeInTheDocument();
    expect(screen.getByText(/connecting/i)).toBeInTheDocument();
  });

  it("renders pushed messages and shows the connected status pill", async () => {
    render(<ChatRoom courseId="c1" token="t" />);
    const ws = MockWebSocket.instances[0];
    expect(ws.url).toContain("/api/v1/chat/ws/c1");

    act(() => ws.simulateOpen());
    await screen.findByText(/connected · 0 online/i);

    act(() => ws.push({ type: "presence", data: { online: ["u1"] } }));
    await screen.findByText(/connected · 1 online/i);

    act(() => ws.push(messageFrame("m1", "hi everyone")));
    expect(await screen.findByText("hi everyone")).toBeInTheDocument();
    expect(screen.getByText("Lina")).toBeInTheDocument();
  });

  it("sends a message frame via the socket when the form submits", async () => {
    render(<ChatRoom courseId="c1" token="t" />);
    const ws = MockWebSocket.instances[0];
    act(() => ws.simulateOpen());

    const user = userEvent.setup();
    await user.type(screen.getByLabelText(/message/i), "hello");
    await user.click(screen.getByLabelText(/send/i));

    expect(ws.sent).toHaveLength(1);
    expect(JSON.parse(ws.sent[0])).toEqual({
      type: "message",
      data: { body: "hello" },
    });
  });

  it("keeps Send disabled while the socket is not open", async () => {
    render(<ChatRoom courseId="c1" token="t" />);
    const sendBtn = screen.getByLabelText(/send/i);
    expect(sendBtn).toBeDisabled();

    await userEvent.setup().type(screen.getByLabelText(/message/i), "draft");
    expect(sendBtn).toBeDisabled();
  });

  it("shows Reconnecting after the socket drops with a retryable code", async () => {
    render(<ChatRoom courseId="c1" token="t" />);
    const ws = MockWebSocket.instances[0];
    act(() => ws.simulateOpen());
    await screen.findByText(/connected/i);

    act(() => ws.close(1006)); // network drop — retryable
    await waitFor(() => expect(screen.getByText(/reconnecting/i)).toBeInTheDocument());
  });

  it("shows Disconnected when the server refuses with a terminal code", async () => {
    render(<ChatRoom courseId="c1" token="t" />);
    const ws = MockWebSocket.instances[0];
    act(() => ws.close(4403)); // server-refused → no retries
    await waitFor(() => expect(screen.getByText(/disconnected/i)).toBeInTheDocument());
  });

  it("does not open a socket when no token is supplied", () => {
    render(<ChatRoom courseId="c1" token={null} />);
    expect(MockWebSocket.instances).toHaveLength(0);
  });
});
