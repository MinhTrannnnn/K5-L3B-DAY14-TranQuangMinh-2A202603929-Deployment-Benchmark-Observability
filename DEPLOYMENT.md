# Deployment Information

## Public URL

https://k5-l3b-day14-tranquangminh-2a202603929-deploymen-production.up.railway.app

## Platform và source

- Railway, project `earnest-freedom`, environment `production`.
- Deploy agent Part 6 từ repo fork `MinhTrannnnn/K5-L3B-DAY14-TranQuangMinh-2A202603929-Deployment-Benchmark-Observability`.
- Root Directory: `/06-lab-complete`.
- Railway Config File: `/06-lab-complete/railway.toml`.
- Agent build bằng Dockerfile; Redis là service riêng trong cùng project.
- Lần deploy đầu chọn nhầm ví dụ Go; đặt đúng root/config rồi deploy thành công.

## Environment Variables Set

- `AGENT_API_KEY`: secret trên Railway, không ghi giá trị vào tài liệu.
- `REDIS_URL`: tham chiếu `${{Redis.REDIS_URL}}`, không chép connection string chứa mật khẩu vào repo.
- `ENVIRONMENT=production`.
- `RATE_LIMIT_PER_MINUTE=10`.
- `DAILY_BUDGET_USD=1`.
- `PORT`: ứng dụng đọc port runtime; không cần cố định theo port local.

## Test Commands

Chạy bằng zsh trên máy học viên. Nhập API key đúng với giá trị đã đặt trên Railway; ký tự được ẩn khi nhập.

```bash
BASE="https://k5-l3b-day14-tranquangminh-2a202603929-deploymen-production.up.railway.app"
read -rs 'AGENT_API_KEY?Nhập API key rồi Enter: '
echo

curl -sS -o /dev/null -w '%{http_code}\n' "$BASE/health"
curl -sS -o /dev/null -w '%{http_code}\n' "$BASE/ready"
curl -sS -o /dev/null -w '%{http_code}\n' -X POST "$BASE/ask" \
  -H 'Content-Type: application/json' -d '{"question":"Hello"}'
curl -sS -o /dev/null -w '%{http_code}\n' -X POST "$BASE/ask" \
  -H "X-API-Key: $AGENT_API_KEY" \
  -H 'Content-Type: application/json' -d '{"question":"What is Docker?"}'
```

Kết quả kiểm chứng ngày 26/11/2026:

| Trường hợp | HTTP | Bằng chứng |
|---|---:|---|
| `GET /health` | 200 | Codex kiểm tra trực tiếp URL public: `{"status":"ok"}`. |
| `GET /ready` | 200 | Codex kiểm tra trực tiếp: `{"ready":true}`, agent kết nối được Redis. |
| `POST /ask` thiếu key | 401 | Codex kiểm tra trực tiếp: `{"detail":"Invalid or missing API key"}`. |
| `POST /ask` có key | 200 | Học viên chạy curl, cung cấp response HTTP/2 200. |

Response có key do học viên cung cấp lúc 13:04:23 UTC (20:04:23 GMT+7):

```json
{"question":"What is Docker?","answer":"Container là cách đóng gói app để chạy ở mọi nơi. Build once, run anywhere!","usage":{"input_tokens":6,"output_tokens":30,"cost_usd":1.89e-05}}
```

LLM là mock; trường cost là chi phí giả lập theo token ước lượng, không phải hóa đơn API thật.

## Screenshots

- [Dashboard](screenshots/dashboard.png): dashboard Railway có agent và Redis, che giá trị secret.
- [Deployment running](screenshots/running.png): deployment agent Active / successful.
- [Public API tests](screenshots/test.png): output 4 lệnh kiểm tra, thấy mã 200, 200, 401, 200.

Đã kiểm tra đủ ba file ảnh trong repo: agent và Redis Online, deployment Active, kết quả API 200 / 200 / 401 / 200; không thấy giá trị secret trong ảnh.
