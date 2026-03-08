"""Public offer and info page endpoints."""

from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse, HTMLResponse

router = APIRouter(tags=["offer"])

_OFFER_PATH = Path(__file__).resolve().parent.parent.parent.parent.parent / "docs" / "pub_oferta.docx"


@router.get("/offer")
async def download_offer() -> FileResponse:
    """Download the public offer document."""
    if not _OFFER_PATH.exists():
        raise HTTPException(status_code=404, detail="Offer document not found")
    return FileResponse(
        path=str(_OFFER_PATH),
        filename="pub_oferta.docx",
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    )


_INFO_HTML = """\
<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>CourseForge — генерация курсовых работ</title>
<style>
  * { margin: 0; padding: 0; box-sizing: border-box; }
  body {
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
    background: #f5f7fa; color: #1a1a2e; line-height: 1.6;
  }
  .container { max-width: 820px; margin: 0 auto; padding: 40px 20px; }
  h1 { font-size: 2em; margin-bottom: 8px; color: #16213e; }
  .subtitle { font-size: 1.1em; color: #555; margin-bottom: 32px; }
  .card {
    background: #fff; border-radius: 12px; padding: 28px 32px;
    margin-bottom: 24px; box-shadow: 0 2px 8px rgba(0,0,0,0.06);
  }
  .card h2 { font-size: 1.25em; margin-bottom: 12px; color: #0f3460; }
  .card p, .card li { font-size: 0.95em; color: #333; }
  .card ul { padding-left: 20px; margin-top: 8px; }
  .card li { margin-bottom: 6px; }
  table {
    width: 100%; border-collapse: collapse; margin-top: 12px;
  }
  th, td {
    padding: 10px 14px; text-align: left; border-bottom: 1px solid #eee;
  }
  th { background: #f0f4ff; font-weight: 600; color: #0f3460; }
  .price { font-weight: 600; color: #16213e; }
  .per-credit { color: #888; font-size: 0.9em; }
  .cta {
    display: inline-block; margin-top: 20px; padding: 12px 28px;
    background: #0f3460; color: #fff; text-decoration: none;
    border-radius: 8px; font-size: 1em; font-weight: 500;
  }
  .cta:hover { background: #1a4a8a; }
  .contacts { font-size: 0.93em; color: #555; }
  .contacts a { color: #0f3460; }
  .footer {
    text-align: center; margin-top: 32px; font-size: 0.85em; color: #999;
  }
</style>
</head>
<body>
<div class="container">

  <h1>CourseForge</h1>
  <p class="subtitle">
    Автоматизированная генерация курсовых работ и научных статей
    с использованием технологий искусственного интеллекта
  </p>

  <div class="card">
    <h2>Описание услуги</h2>
    <p>CourseForge — сервис, который генерирует учебные текстовые материалы
       на основе заданных параметров (тема, дисциплина, объём).</p>
    <ul>
      <li>Глубокий анализ темы с поиском и ранжированием источников</li>
      <li>Написание академического текста со ссылками на источники</li>
      <li>Автоматическая проверка фактов</li>
      <li>Форматирование по ГОСТ 7.32-2017</li>
      <li>Результат — документ в формате .docx</li>
    </ul>
    <p style="margin-top:12px; font-size:0.88em; color:#888;">
      Сгенерированные материалы носят справочно-информационный характер
      и предназначены для использования в качестве основы
      для самостоятельной работы.
    </p>
  </div>

  <div class="card">
    <h2>Стоимость</h2>
    <p>Единица тарификации — <b>кредит</b>. Один кредит = один сгенерированный документ.</p>
    <table>
      <thead>
        <tr><th>Пакет</th><th>Цена</th><th>За кредит</th></tr>
      </thead>
      <tbody>
        <tr>
          <td>1 кредит</td>
          <td class="price">199 руб.</td>
          <td class="per-credit">199 руб.</td>
        </tr>
        <tr>
          <td>3 кредита</td>
          <td class="price">549 руб.</td>
          <td class="per-credit">183 руб.</td>
        </tr>
        <tr>
          <td>5 кредитов</td>
          <td class="price">849 руб.</td>
          <td class="per-credit">170 руб.</td>
        </tr>
        <tr>
          <td>10 кредитов</td>
          <td class="price">1 490 руб.</td>
          <td class="per-credit">149 руб.</td>
        </tr>
      </tbody>
    </table>
    <p style="margin-top:10px; font-size:0.88em; color:#888;">
      НДС не облагается (специальный налоговый режим).
      Новым пользователям — 1 бесплатный кредит.
    </p>
  </div>

  <div class="card">
    <h2>Оплата и возврат</h2>
    <p>Оплата производится в безналичной форме через платёжный сервис
       <b>Робокасса</b> (ООО «Робокасса», ОГРН 1137746090786).
       Кредиты зачисляются автоматически после подтверждения платежа.</p>
    <p style="margin-top:10px;"><b>Возврат средств:</b></p>
    <ul>
      <li>Неиспользованные кредиты — возврат 100%, обращение в течение 14 дней с оплаты</li>
      <li>Некачественная услуга — возврат 100% или повторная генерация, обращение в течение 7 дней</li>
      <li>Использованные кредиты с надлежащим результатом — возврату не подлежат</li>
    </ul>
    <p style="margin-top:8px; font-size:0.9em;">
      Заявка на возврат: <a href="mailto:4gg528@gmail.com">4gg528@gmail.com</a>
      с указанием причины и номера заказа.
    </p>
  </div>

  <div class="card">
    <h2>Контактные данные</h2>
    <p class="contacts">
      Исполнитель: <b>Сабитов Тимур Булатович</b>
        (плательщик налога на профессиональный доход)<br>
      ИНН: 593002872645<br>
      Телефон: <a href="tel:+79969527040">+7 996 952-70-40</a><br>
      E-mail: <a href="mailto:4gg528@gmail.com">4gg528@gmail.com</a><br>
      Telegram-бот: <a href="https://t.me/cursachizibot">@cursachizibot</a>
    </p>
  </div>

  <div style="text-align:center;">
    <a class="cta" href="https://t.me/cursachizibot">Открыть бот в Telegram</a>
    <br>
    <a href="/api/offer"
       style="display:inline-block; margin-top:12px; font-size:0.9em; color:#0f3460;">
      Публичная оферта (скачать .docx)
    </a>
  </div>

  <p class="footer">
    &copy; 2026 CourseForge. Все права защищены.
  </p>

</div>
</body>
</html>
"""


@router.get("/info", response_class=HTMLResponse)
async def info_page() -> str:
    """Public info page with service description, pricing, and contacts."""
    return _INFO_HTML
