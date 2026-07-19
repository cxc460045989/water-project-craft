# ⚠️ 不建议清除 — 稳定备份

**日期**: 2026-07-19  
**备份原因**: 串口指令发送逻辑重大优化 + 称重/追加样品全流程，已通过真机验证的稳定版本

---

## 备份文件清单

### 串口协议层
| 文件 | 大小 | 说明 |
|------|------|------|
| protocol_layer.py | 17 KB | send_cmd_with_uplink_check 重写 |

### 称重称量流程
| 文件 | 大小 | 说明 |
|------|------|------|
| weigh_controller.py | 45 KB | 称重控制器（批量+单独） |
| batch_weigh_module.py | — | 批量称重模块 |
| weigh_dialog.py | — | 称量进度弹窗 UI |
| weight_check_dialog.py | — | 重量检查对话框 |

### 追加样品流程
| 文件 | 大小 | 说明 |
|------|------|------|
| sample_append.py | — | 追加样品串口流程 |
| append_sample_worker.py | — | 追加样品 QThread 版 |

### 测试流程
| 文件 | 大小 | 说明 |
|------|------|------|
| test_controller.py | 56 KB | 测试主流程状态机 |

---

## 关键修改摘要

### protocol_layer.py — send_cmd_with_uplink_check
1. 发送前等上行帧（确认仪器空闲）
2. ACK 子串匹配 `raw.find(expected)` 
3. 200ms 重发窗口
4. TARE 前延时 1s
5. _poll_sleep 防 Mock 死锁
6. 详细诊断日志

### test_controller.py
1. _process_sleep 主线程安全

### weigh_controller.py
1. 近零判定 ±0.0050 → 置 0
2. 追加样品模式跳过近零判定

---

**⚠️ 此目录请勿在瘦身清理时删除！**
