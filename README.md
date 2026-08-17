# Canopy Disease

番茄**叶部病虫害**检测 + **温室环控联动** Demo（替代成熟度版 Canopy Assist 作为产品主线）。

仓库：https://github.com/daguaishou0110/wenshi

## 多温室联动模拟

页面是 **Canopy Disease Farm**：四个大棚（H1–H4）拓扑相连。

```
选中某个大棚（H1–H4）
  → 叶面扫描（TL-BS）
  → 本棚 primary 环控预案
  → 邻棚 neighbour spillover（传染性病种：隔离旗 + 温和干棚/通风）
  → Apply linked plan → 多棚 soft-PLC 一并更新 + 审计
  → （可选）农场级 LLM 农事建议
```

| 病种信号 | 本棚 | 邻棚联动 |
|----------|------|----------|
| 晚疫病 / 叶霉 / 细菌性斑点等传染性 | 强降湿、开窗、加风机、关雾化 | 较温和预防 + quarantine 旗 |
| 红蜘蛛 | 避免过度干燥 | 不强推干棚 |
| 病毒 | 卫生/拔除为主 | 限制跨棚人员工具流动提示 |
| 健康 / 未检出 | 不改设定 | 无 spillover |

真实产线把 `greenhouse.apply_plan` 换成 MQTT / Modbus / 厂商 API 即可。

## 本地运行

```bash
pip install -r requirements.txt
# 可选：复制 .env.example 为 .env，填入 OPENCLAW_API_KEY 以启用 advisory
python app.py
```

浏览器打开 http://127.0.0.1:8899

## Deploy on Render

仓库已含 `render.yaml`。任选其一：

### A. Blueprint（推荐）

1. 打开 [Render Dashboard](https://dashboard.render.com/) → **New** → **Blueprint**
2. 连接 GitHub 仓库 `daguaishou0110/wenshi`
3. 确认加载 `render.yaml`，创建服务 `canopy-disease`
4. 在 Environment 中填入 `OPENCLAW_API_KEY`（可选；不填也能跑检测与环控，只是没有 LLM 建议）
5. Deploy 完成后访问 `https://<service-name>.onrender.com`

### B. 手动 Web Service

| 项 | 值 |
|----|----|
| Runtime | Python 3 |
| Build Command | `pip install -r requirements.txt` |
| Start Command | `uvicorn app:app --host 0.0.0.0 --port $PORT` |
| Health Check Path | `/api/config` |

说明：免费实例闲置会休眠，首次打开可能要等几十秒。若 ONNX 推理内存不足，把 plan 升到 Starter。

## 与章节素材对应

- 主推权重：`weights/best.onnx` ← C05 TL-BS
- 实验/成稿备份：本地 `tomato_leaf_experiment_backup`（C05 + C01）
- 旧成熟度 Demo：本地 `tomato_deploy`（保留对照）
