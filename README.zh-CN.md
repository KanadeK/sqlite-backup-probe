# sqlite-restore-drill

对已有 SQLite 备份做一次隔离恢复检查：把普通或 gzip 文件恢复到临时目录，
验证数据库结构、外键，并按 JSON 合约检查表、字段、行数和应用版本。
不连接生产数据库，不覆盖原备份，不需要服务器或第三方运行时依赖。

```sh
python -m pip install .
python examples/demo.py
python -m sqlite_restore_drill backup.sqlite.gz --contract expectations.json
```

合约格式、安装步骤和参数见 [英文 README](README.md)。退出码 0 表示请求的检查通过，
1 表示备份或约束检查失败，2 表示输入、配置或 I/O 错误。输出为 JSON，不含行数据。

必须使用已经独立封装好的备份；带 WAL、SHM、journal 旁文件时会拒绝处理。
普通复制线上主数据库可能漏掉 WAL 数据，本工具无法从已丢失的 WAL 推断缺少了什么。
默认原文件与解压文件分别限制在 512 MiB，超时 30 秒为协作式检查，不能中断所有系统 I/O。
不检查业务正确性、备份新鲜度，也不替代完整灾难恢复演练。

使用 `python -m pip uninstall sqlite-restore-drill` 卸载；临时恢复目录正常完成后自动清理。
不要把删除真实备份当作卸载步骤。MIT 许可证，Python 3.11+。
