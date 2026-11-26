# Benchmark & Observability Report — Day 14

> Kết quả lấy từ JSON/CSV, Prometheus, Jaeger và ảnh chụp thực tế; các phép đo mock không phải chi phí API thật.
> Mọi con số phải lấy từ report JSON / CSV / screenshot thật, không ước lượng.

**Họ tên:** Trần Quang Minh — K5-L3B — 2A202603929
**Ngày chạy:** 26/11/2026 (GMT+7).
**Môi trường:** macOS 26.5.2, Apple Silicon (`Mac16,1`), 10 CPU logical, RAM máy 16 GiB; Docker Engine 29.6.1, Docker VM 10 CPU / khoảng 7.75 GiB RAM. Develop dùng Python 3.12.14; container Python 3.11 slim. Agent production giới hạn 0.5 CPU / 256 MiB mỗi instance theo Compose.

---

## 0. Exercise 7.1 — Metrics cơ bản

Học viên chạy agent v1 tại port 8001 và v2 tại 8002. Request gửi tới v2 trả lời về Prometheus với `agent_version=v2`, `model=mock-llm-small`; response ghi input 91 token, output 55 token, chi phí giả lập 0.00004665 USD và LLM latency 188.6 ms.

Output metrics học viên cung cấp:

```text
http_requests_total{method="POST",route="/ask",status="200"} 1.0
agent_question_length_chars_bucket{le="20.0"} 0.0
agent_question_length_chars_bucket{le="50.0"} 1.0
agent_question_length_chars_count 1.0
agent_question_length_chars_sum 40.0
agent_in_flight_requests 0.0
```

- **Counter:** `http_requests_total` đếm request, hiện có 1 request POST `/ask` trả 200.
- **Gauge:** `agent_in_flight_requests` tăng/giảm theo request đang xử lý, tại thời điểm scrape bằng 0.
- **Histogram:** `agent_question_length_chars` đo độ dài câu hỏi; count 1, sum 40 ký tự. Bucket là tích lũy: câu hỏi dài 40 không nằm trong bucket ≤20, nằm trong bucket ≤50 và mọi bucket lớn hơn.
- Đã thêm histogram với buckets 20, 50, 100, 200, 500, 1000, 2000; không đưa độ dài hoặc nội dung câu hỏi vào label.
- **Vì sao dùng route template:** URL không khớp route được gom vào `unmatched`. Nếu dùng URL thô làm label, bot quét hàng nghìn đường dẫn sẽ tạo rất nhiều time series khác nhau, tăng RAM/storage và chi phí truy vấn Prometheus (high cardinality).

## 1. SLO của agent

| SLI | SLO | Lý do chọn ngưỡng này |
|---|---|---|
| p95 latency `/ask` | ≤ 500 ms | Ngưỡng mặc định của load test, theo dõi trải nghiệm của phần lớn request. |
| Error rate `/ask` | ≤ 2% | Ngưỡng mặc định của load test, giới hạn tỷ lệ request không thành công. |
| Accuracy trên golden dataset | ≥ 85% (CI); 100% sau sửa KB | Quality gate CI và mục tiêu bài eval cuối. |

---

## 2. Benchmark hiệu năng (develop, `load_test.py`)

### 2.1 Concurrency vs latency (agent v2)

| Concurrency | RPS | p50 (ms) | p95 (ms) | p99 (ms) | Error rate | SLO |
|---|---|---|---|---|---|---|
| 1 | 4.22 | 194.4 | 222.3 | 1700.1 | 1.00% | PASS |
| 10 | 47.08 | 190.6 | 219.8 | 1661.6 | 2.00% | PASS |
| 50 | 107.2 | 191.1 | 230.8 | 1705.5 | 0.67% | PASS |
| 100 | 60.24 | 337.0 | 3111.3 | 4099.0 | 0.67% | FAIL (p95) |

**Nhận xét:** RPS không tăng tuyến tính: từ 4.22 ở concurrency 1 lên 107.2 ở 50, rồi giảm còn 60.24 ở 100. Tại mức 100, p95 tăng từ 230.8 lên 3111.3 ms, vượt SLO dù error rate chỉ 0.67%. Kết quả cho thấy tăng concurrency quá cao trong lượt đo này làm throughput giảm và tail latency tăng mạnh. Có thể liên quan tài nguyên máy, lập lịch, kết nối hoặc client/server bị nghẽn; chưa có CPU/profile để kết luận chính xác nút thắt. Mỗi mức chỉ chạy 300 request, có slow/error ngẫu nhiên nên không xem tỷ lệ này là đặc tính cố định của hệ thống.

Bằng chứng: `reports/load_v2_c1.json`, `load_v2_c10.json`, `load_v2_c50.json`, `load_v2_c100.json`; các giá trị trong bảng lấy trực tiếp từ JSON. Mức concurrency 10 có error rate đúng 2% vẫn PASS vì script so sánh ≤, không phải <.

### 2.2 Tail latency

| `MOCK_SLOW_RATE` | avg (ms) | p95 (ms) | p99 (ms) |
|---|---|---|---|
| 0 | 188.5 | 214.5 | 220.8 |
| 0.03 (mặc định) | 230.1 | 220.6 | 1685.5 |
| 0.1 | 304.9 | 1681.5 | 1711.9 |

**Nhận xét:** Khi slow rate từ 0 lên 0.03, avg chỉ tăng 188.5 → 230.1 ms nhưng p99 tăng 220.8 → 1685.5 ms; p95 vẫn 220.6 ms nên SLO PASS. Ở slow rate 0.1, avg là 304.9 ms nhưng p95 đạt 1681.5 ms và p99 1711.9 ms, trượt SLO p95 ≤500 ms. Error rate tương ứng 1.67%, 0.67%, 1.67%, đều đạt ngưỡng ≤2%.

p99 nhạy với phần đuôi chậm hơn p95 khi tỷ lệ request chậm còn nhỏ. Khi tỷ lệ chậm tăng đủ lớn, p95 cũng tăng mạnh. Average gộp nhiều request nhanh với số ít request chậm nên dễ che trải nghiệm xấu ở phần đuôi; cần SLO theo percentile cùng error rate. Slow/error trong mock là ngẫu nhiên, không kỳ vọng chính xác 3% hoặc 10% trên mỗi mẫu 300 request.

Bằng chứng: ba file `reports/load_v2_slow_0.json`, `load_v2_slow_0.03.json`, `load_v2_slow_0.1.json`; cùng concurrency 20 và 300 request.

---

## 3. Benchmark chất lượng (develop, `eval/run_eval.py`)

| Chỉ số | Agent v1 | Agent v2 | Agent v2 (sau khi sửa KB) |
|---|---|---|---|
| Accuracy | 4.3% (1/23) | 91.3% (21/23) | 100.0% (23/23) |
| Avg tokens / câu | 56.0 | 109.1 | 117.1 |
| Tổng cost (USD) | 0.00039 | 0.000762 | 0.00082 |
| Cost / câu đúng (USD) | 0.00038955 | 3.627e-05 | 3.566e-05 |
| Quality gate | FAIL (85%) | PASS (85%, 0 regression) | PASS (100%, 0 regression) |

**Những câu v2 trả lời sai ban đầu và cách bạn sửa:**

| ID | Keyword bị thiếu | Bạn đã sửa gì |
|---|---|---|
| security-02 | token, hết hạn, chữ ký | Thêm tài liệu phân biệt API key/JWT, chữ ký, claims và thời hạn. |
| scaling-03 | cpu, memory, custom metrics | Thêm tài liệu Kubernetes HPA và các chỉ số autoscaling. |

**Nhận xét về trade-off chất lượng / chi phí / latency giữa v1 và v2:** v1 đúng 1/23, v2 đúng 21/23, cải thiện 20 câu và không regression. Retrieval tăng avg tokens 56.0 → 109.1, p95 184.1 → 213.8 ms và tổng cost. Tuy nhiên cost/câu đúng giảm từ 0.00038955 xuống 0.00003627 USD, nên v2 hiệu quả hơn khi xét chất lượng. Đây là số đo mock và keyword-based eval, không đại diện độ chính xác của một LLM thực.

**Quality gate CI:** đã thêm workflow [.github/workflows/eval.yml](.github/workflows/eval.yml) chạy khi push main hoặc pull request, bật v2 với lỗi/slow ngẫu nhiên tắt và đợi healthcheck; chạy `run_eval.py --min-accuracy 0.85 --baseline <report baseline đã duyệt>` trong job sau khi agent sẵn sàng. Script trả exit code 1 khi accuracy thấp hơn ngưỡng hoặc có regression; không bỏ qua exit code và đặt job làm required status check trong branch protection để chặn merge khi fail. Kiểm tra cuối lab dùng ngưỡng 1.0 và baseline v2 trước sửa KB. Học viên đã restart v2 và chạy eval cuối: 23/23, errors 0, regression 0, quality gate 100% PASS. p95 215.3 ms, avg tokens 117.1; hai câu thiếu kiến thức đã được cải thiện. Bằng chứng: `reports/eval_v1.json`, `reports/eval_v2.json`, `reports/eval_v2_fixed.json`.

---

## 4. Observability stack (production)

**Khởi động stack:** agent ban đầu restart vì `ModuleNotFoundError: No module named uvicorn`. Dockerfile copy packages vào `/home/agent/.local`, nhưng home user là `/app`. Đã thêm `ENV PYTHONUSERBASE=/home/agent/.local`, rebuild agent và recreate Nginx. Kiểm tra trực tiếp bằng Docker: agent healthy, các service khác Up; `/health` qua Nginx trả 200. Ảnh dashboard giai đoạn đầu được chụp với 1 agent; benchmark scale 1/3 instance được trình bày riêng tại mục 5.

### 4.1 Screenshot

Dashboard Grafana đã hiển thị tải từ Locust. File ảnh đã lưu ghi nhận traffic 18.7 req/s, error rate 0.49%, latency p95 294.98 ms, saturation 5 và 1 instance. Biểu đồ có p99 khoảng 1.8 giây trong khi p95 dưới 300 ms, cho thấy phần đuôi chậm. Đây là số tại thời điểm chụp, không thay thế kết quả load test JSON. Đọc chính xác avg/p95 từ lịch sử Prometheus và đánh giá phân bố tải nhiều instance ở mục 4.4–5.

Đã lưu [grafana-dashboard.png](screenshots/grafana-dashboard.png).

- [x] [Dashboard Grafana khi đang có tải](screenshots/grafana-dashboard.png).
- [x] [Trace chậm: 1.9 giây, span LLM 1.7 giây](screenshots/jaeger-slow-trace.png), chụp trực tiếp Jaeger bằng Chrome headless từ trace đã lưu.
- [x] [Trace lỗi có event exception](screenshots/jaeger-error-trace.png).
- [x] [Hai alert cùng Firing](screenshots/prometheus-alert-firing.png).


Ảnh tìm kiếm cũ được giữ riêng trong `evidence/part7/extra-screenshots/`, không dùng thay ảnh chi tiết trace.

Unit test alert rules bằng `promtool test rules`: **SUCCESS**, exit code 0. [Output kiểm tra](evidence/part7/alert-rule-unit-test.txt).

### 4.2 Thí nghiệm "phá hệ thống"

| # | Thay đổi | Alert nào firing | Thời gian từ lúc đổi → firing | Panel nào phản ánh rõ nhất |
|---|---|---|---|---|
| A | Chỉ tăng `MOCK_ERROR_RATE=0.2`, giữ `MOCK_SLOW_RATE=0.03` | AgentHighErrorRate; latency alert inactive | Khoảng 95.5 giây từ container start đến mẫu quan sát firing đầu (poll 5 giây) | Error rate /ask |
| B | `MOCK_SLOW_RATE=0.3` (đồng thời error rate 0.2) | AgentHighLatencyP95 | Khoảng 139.3 giây từ container start đến mẫu firing đầu | p95 latency /ask |
| C | `LLM_MODEL=mock-llm-large` | Chưa thực hiện | — | — |
| D | `docker pause` 1 instance | Chưa thực hiện | — | — |
| E | `AGENT_VERSION=v1` | Phân tích lý thuyết, chưa chạy thí nghiệm | — | Accuracy eval |

**Phân tích thí nghiệm:** có hai cấu hình khác nhau: A chỉ tăng lỗi 20% và giữ slow rate 3%; B tăng cả lỗi 20% và slow rate 30%, ảnh học viên cho thấy cả hai alert cùng Firing. Ở A, error alert firing trong khi latency alert vẫn inactive, phù hợp việc tỷ lệ lỗi tăng riêng. Đã khôi phục cấu hình thường sau thử nghiệm A. Bằng chứng A: [error-only-experiment.json](evidence/part7/error-only-experiment.json) và [log chạy](evidence/part7/error-only-experiment.log). API Prometheus xác nhận error rate khoảng 19.88% và p95 khoảng 1.883 giây tại thời điểm thu bằng chứng. Hai biến thay đổi đồng thời nên chưa tách riêng ảnh hưởng nhân quả; ví dụ lỗi upstream cũng góp vào phân bố latency.

Ngưỡng error >5% cần duy trì 1 phút; p95 >1 giây cần duy trì 2 phút. Thời gian B được tính từ Docker StartedAt `2026-11-26T16:03:25.948999801Z` (error alert B firing sau khoảng 84.3 giây), không phải thời điểm bắt đầu gõ lệnh; mẫu firing đầu truy vấn lại theo bước 5 giây nên có sai số theo chu kỳ đánh giá/lấy mẫu. `activeAt` là lúc bắt đầu active/pending, không phải thời điểm firing. Đã lưu [trạng thái rules](evidence/part7/prometheus-alert-rules.json), [lịch sử firing](evidence/part7/alert-firing-history.json), [mốc container](evidence/part7/chaos-container.json).

**Vì sao cost alert trước đó firing nhưng sau đó inactive?** Burn rate được tính từ tốc độ tăng chi phí trong cửa sổ 5 phút. Tải/chậm/lỗi thay đổi có thể làm throughput request thành công giảm và rate chi phí xuống dưới ngưỡng; cost alert không chỉ phụ thuộc model. Chưa khẳng định một nguyên nhân duy nhất từ ảnh.

**Thí nghiệm E không làm alert nào firing. Bạn sẽ phát hiện loại sự cố này trong production bằng cách nào?** Metrics hạ tầng như latency, error rate và cost không đo trực tiếp chất lượng nội dung. Cần eval golden dataset làm quality gate trước deploy, chạy eval định kỳ/canary hoặc kiểm tra mẫu phản hồi bằng bộ chấm chất lượng; theo dõi accuracy/regression và phản hồi người dùng. Không coi HTTP 200 là bằng chứng câu trả lời đúng.

### 4.3 Debug bằng trace

Chọn 1 trace chậm nhất bạn tìm được:

- `trace_id`: `d2f82a0a2b6d0a4c6d9cc2195dc308e3`
- Tổng thời gian: 1930.689 ms (span HTTP).
- Bước nghiệp vụ chiếm nhiều thời gian nhất: `chat mock-llm-small` (1693.929 ms, 87.74% tổng trace). Span retrieval 224.001 ms; `agent.run` là span cha bao cả retrieval và LLM, không cộng các span cha/con để tính tổng.
- Dòng log tương ứng (grep theo `trace_id`):

```json
{"ts": "2026-11-26T15:54:37.603201+00:00", "level": "INFO", "service": "observable-agent", "instance": "afc212752ffe", "event": "llm_call", "trace_id": "d2f82a0a2b6d0a4c6d9cc2195dc308e3", "span_id": "5b06224a786e63b9", "request_id": "297327f28369", "model": "mock-llm-small", "agent_version": "v2", "input_tokens": 81, "output_tokens": 46, "cost_usd": 4e-05, "llm_ms": 1693.5}
```

Đã lấy JSON từ Jaeger và đối chiếu trace ID với log agent: [slow-trace.json](evidence/part7/slow-trace.json), [slow-trace-log.jsonl](evidence/part7/slow-trace-log.jsonl). Thời gian `llm_ms` trong log đo ở phạm vi mock; thời gian span gồm overhead instrumentation nên có thể khác nhẹ.

---


**Trace lỗi:** `26cc799ab934ee673114300aca71b4c6`, HTTP 503; ảnh học viên cho thấy span `chat mock-llm-small` có `error.type=upstream_unavailable` và event `exception` với thông báo `Upstream LLM error: 503 Service Unavailable (mock)`. Retrieval hoàn thành, lỗi phát sinh ở bước gọi LLM. Bằng chứng JSON/log: [error-trace.json](evidence/part7/error-trace.json), [error-trace-log.jsonl](evidence/part7/error-trace-log.jsonl). Đã lưu [ảnh trace lỗi và exception](screenshots/jaeger-error-trace.png).

### 4.4 Trả lời Exercise 7.4

1. **p95 và avg:** snapshot Prometheus truy vấn tại `2026-11-26T15:49:00Z` (22:49 GMT+7) cho p95 **296.83 ms**, avg **250.33 ms**. Đây là mẫu truy vấn lịch sử riêng, không gán hai giá trị này cho đúng pixel thời điểm ảnh Grafana. p99 trên ảnh khoảng 1.8 giây trong khi p95/avg thấp hơn nhiều, cho thấy một phần nhỏ request rất chậm.
2. **Chia tải giữa instance:** ảnh Grafana ban đầu chỉ có 1 instance nên chưa thể kết luận chia đều. Phần benchmark được kiểm chứng lại với đúng 1/3 instance và có log số container; phân bố request theo instance được ghi cùng bằng chứng Prometheus ở mục 5. Snapshot khi benchmark 3 instance cho RPS theo instance **20.55 / 20.56 / 20.71**: lưu lượng gần đều. Prometheus xác nhận cả 3 target up=1. Round-robin chia lượt request, không đảm bảo latency hoặc số request đang xử lý của các instance bằng nhau. Bằng chứng: [three-instance-metrics.json](evidence/part7/three-instance-metrics.json).
3. **Input tokens/s lớn hơn output:** prompt gồm system prompt + tài liệu retrieval + câu hỏi, còn output chỉ là đoạn trả lời; v2 vì vậy có thể dùng nhiều input token hơn output. Snapshot benchmark 3 instance đo input khoảng **4570.21 token/s**, output **2429.11 token/s**. Chỉ số thực tế còn phụ thuộc độ dài tài liệu/câu trả lời và số request thành công; không phải quy luật bắt buộc cho mọi model.
4. **`curl http://localhost:8080/metrics`:** Nginx cấu hình `location = /metrics { return 404; }`, nên endpoint public trả **404**. Prometheus scrape `/metrics` trực tiếp từng agent:8000 trên Docker network, không qua route public; tránh lộ metric qua cổng client.

## 5. Benchmark scaling (production, Locust headless, 100 users, 2 phút)

| Số instance | RPS `/ask` | p50 (ms) | p95 (ms) | p99 (ms) | Failures `/ask` |
|---|---|---|---|---|---|
| 1 | 59.39 | 200 | 280 | 1700 | 66/7091 (0.93%) |
| 3 | 59.76 | 190 | 230 | 1700 | 74/7131 (1.04%) |

Bảng lấy đúng hàng POST `/ask` từ CSV đã nộp, không trộn GET `/health`. Đây là **hai lượt chạy kiểm chứng cuối**: Docker ghi nhận đúng 1 hoặc 3 agent trước khi chạy và kiểm tra lại mỗi 10 giây trong toàn bộ lượt đo. Cả hai dùng cùng mock model nhỏ, error rate 0.01, slow rate 0.03, 100 user, ramp-up 10 user/s và 2 phút. Locust web được dừng trước khi chạy headless.

**Cách chạy tránh thay đổi replica ngoài ý muốn:** sau khi đặt `--scale agent=N`, chạy Locust bằng `docker compose -p k5-day14-observability run --rm --no-deps locust ...`. Nếu thiếu `--no-deps`, Compose có thể đưa agent về `deploy.replicas=2`; hai lượt học viên chạy trước đó được đối chiếu lịch sử Prometheus và xác định đều có 2 instance. Các CSV cũ được lưu riêng trong `evidence/part7/initial-scaling-2-instances/`, không dùng cho bảng này.

**Giải thích kết quả:** RPS `/ask` thay đổi khoảng +0.63% khi tăng 1 → 3 instance; p95 giảm 280 → 230 ms (khoảng 17.9%), p50 giảm 200 → 190 ms còn p99 giữ 1700 ms. Đây là một lượt đo mỗi cấu hình, chưa chứng minh mức cải thiện ổn định qua nhiều lần lặp. p95/p99 vẫn chịu ảnh hưởng latency giả lập và tail delay của mock. Locust dùng 100 user với think time 0.5–2 giây nên tải này có thể chưa bão hòa một instance; scale không nhất thiết tăng throughput gấp ba hoặc giảm thời gian chờ LLM mỗi request. Chưa có profiling để kết luận nút thắt CPU cụ thể. Lỗi 503 là upstream mock và Locust trả exit code 1 khi có request failure, không tự suy ra container crash. Percentile CSV được xấp xỉ và CSV là snapshot gần cuối, nên terminal shutdown có thể hiển thị thêm vài request.

Bằng chứng: [scale_1_stats.csv](benchmark-results/scale_1_stats.csv), [scale_3_stats.csv](benchmark-results/scale_3_stats.csv), [runtime instance audit](evidence/part7/verified-scaling-runtime.json), [log 1 instance](evidence/part7/scale_1_verified.log), [log 3 instance](evidence/part7/scale_3_verified.log).

---

## 6. Kết luận

1. Average che giấu tail latency: chỉ 3% request chậm đã đẩy p99 lên khoảng 1.7 giây; cần đo percentile và error rate theo cùng điều kiện tải.
2. RAG tăng token và tổng chi phí nhưng cải thiện accuracy 1/23 → 23/23, làm cost/câu đúng giảm mạnh; cần quality gate để phát hiện regression mà HTTP metrics không thấy.
3. Metrics xác định triệu chứng, trace chỉ ra bước tốn thời gian, log có trace ID giúp đối chiếu request; alert cần ngưỡng và thời gian duy trì để tránh báo động vì spike.

Nếu vận hành thật, bổ sung alert về accuracy/canary và retrieval hit rate, Redis availability, tỷ lệ timeout/retry, ngân sách theo tenant, cùng error-budget burn rate. Cần bảo vệ metrics nội bộ, tránh label cardinality cao và giữ trước ngân sách cho các request đồng thời. Không suy rộng kết quả mock thành năng lực phục vụ LLM thật.
