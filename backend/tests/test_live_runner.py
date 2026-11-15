import urllib.request
import json
import time
import hmac
import hashlib

SECRET = "local_test_secret_abc123_xyz"
BASE_URL = "http://127.0.0.1:8088"


def send_signed(payload, skew=0, signature_override=None):
    ts = str(int(time.time()) + skew)
    body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    sig = signature_override or hmac.new(
        SECRET.encode("utf-8"),
        f"{ts}.".encode("utf-8") + body,
        hashlib.sha256,
    ).hexdigest()

    req = urllib.request.Request(
        f"{BASE_URL}/execute",
        data=body,
        headers={
            "Content-Type": "application/json",
            "X-CodePilot-Timestamp": ts,
            "X-CodePilot-Signature": sig,
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode("utf-8"))


def run_tests():
    print("--- 1. Testing Python Execution via Live Runner ---")
    status, res = send_signed({
        "code": "name = input()\nprint(f'Hello from Runner, {name}!')",
        "language": "python",
        "stdin": "Mohit",
    })
    print(f"Status: {status}, Execution: {res.get('status')}, Output: {res.get('stdout', '').strip()!r}, Duration: {res.get('duration_ms', 0):.1f}ms")
    assert status == 200 and res["status"] == "success"

    print("\n--- 2. Testing C++ Execution via Live Runner ---")
    cpp_code = "#include <iostream>\nint main(){ std::string s; std::cin >> s; std::cout << \"C++ Runner: \" << s << std::endl; return 0; }"
    status, res = send_signed({
        "code": cpp_code,
        "language": "cpp",
        "stdin": "ExecutionVerified",
    })
    print(f"Status: {status}, Execution: {res.get('status')}, Output: {res.get('stdout', '').strip()!r}, Duration: {res.get('duration_ms', 0):.1f}ms")
    assert status == 200 and res["status"] == "success"

    print("\n--- 3. Testing Java Execution via Live Runner ---")
    java_code = "import java.util.Scanner;\npublic class Main {\n    public static void main(String[] args) {\n        Scanner sc = new Scanner(System.in);\n        System.out.println(\"Java Runner: \" + sc.next());\n    }\n}"
    status, res = send_signed({
        "code": java_code,
        "language": "java",
        "stdin": "DockerVerified",
    })
    print(f"Status: {status}, Execution: {res.get('status')}, Output: {res.get('stdout', '').strip()!r}, Duration: {res.get('duration_ms', 0):.1f}ms")
    assert status == 200 and res["status"] == "success"

    print("\n--- 4. Testing Invalid Signature Rejection ---")
    status, res = send_signed(
        {"code": "print(1)", "language": "python"},
        signature_override="bad_signature_hex_1234567890abcdef",
    )
    print(f"Status: {status}, Detail: {res.get('detail')}")
    assert status == 401

    print("\n--- 5. Testing Expired Timestamp Rejection ---")
    status, res = send_signed(
        {"code": "print(1)", "language": "python"},
        skew=-45,
    )
    print(f"Status: {status}, Detail: {res.get('detail')}")
    assert status == 401

    print("\n--- 6. Testing Anti-Replay Protection ---")
    ts = str(int(time.time()))
    body = json.dumps({"code": "print('replay_test')", "language": "python"}, separators=(",", ":")).encode("utf-8")
    sig = hmac.new(SECRET.encode("utf-8"), f"{ts}.".encode("utf-8") + body, hashlib.sha256).hexdigest()
    req1 = urllib.request.Request(
        f"{BASE_URL}/execute",
        data=body,
        headers={"Content-Type": "application/json", "X-CodePilot-Timestamp": ts, "X-CodePilot-Signature": sig},
        method="POST",
    )
    with urllib.request.urlopen(req1) as r1:
        s1 = r1.status
    try:
        req2 = urllib.request.Request(
            f"{BASE_URL}/execute",
            data=body,
            headers={"Content-Type": "application/json", "X-CodePilot-Timestamp": ts, "X-CodePilot-Signature": sig},
            method="POST",
        )
        urllib.request.urlopen(req2)
        s2, d2 = 200, "Unexpected success"
    except urllib.error.HTTPError as e:
        s2, d2 = e.code, json.loads(e.read().decode("utf-8")).get("detail")
    print(f"First request: {s1}, Second request (replay): {s2}, Detail: {d2}")
    assert s1 == 200 and s2 == 401

    print("\nAll live runner tests completed successfully!")


if __name__ == "__main__":
    run_tests()
