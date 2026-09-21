"""Per-batch file success rates; pending/filtered files are not failures."""


def file_statistics(entries):
    entries = list(entries)
    attempted = [e for e in entries if e['status'] in ('success', 'error')]
    read_ok = [e for e in attempted if e['status'] == 'success']
    successful = len(read_ok)
    total = len(attempted)
    return {'processed': total, 'successful': successful, 'failed': total-successful,
            'filtered': sum(e['status'] == 'filtered' for e in entries),
            'success_rate_percent': successful / total * 100 if total else None,
            'basis': 'file_extraction'}


def rate_text(stats):
    value = stats['success_rate_percent']
    return '—' if value is None else f'{value:.1f}%'


def summary_text(stats, *, stopped=False, skipped=0):
    text = f"成功 {stats['successful']} · 失败 {stats['failed']} · 提取成功率 {rate_text(stats)}"
    if stopped: text = '已停止 · ' + text
    if skipped: text += f' · 未处理 {skipped}'
    if stats['filtered']: text += f" · 已过滤 {stats['filtered']}"
    return text
