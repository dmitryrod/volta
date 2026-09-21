__all__ = ["generate_text"]

from unicex.enums import Exchange, MarketType
from unicex.extra import (
    generate_cg_link,
    generate_ex_link,
    generate_tv_link,
    make_humanreadable,
    normalize_symbol,
)

from app.models import ScreeningResult, SettingsDTO
from app.schemas import TextTemplateType
from app.utils.coinmarketcap_rank import get_cmc_rank_for_symbol


def _fmt_pct(value: float) -> str:
    return f"{value:.2f}%"


def _fmt_coins(value: float) -> str:
    return f"{make_humanreadable(value)}¢"


def _fmt_dollars(value: float) -> str:
    return f"{make_humanreadable(value)}$"


def _fmt_multiplier(value: float) -> str:
    return f"{value:.1f}x"


def _generate_tree_type_text(
    symbol: str,
    exchange: Exchange,
    market_type: MarketType,
    settings: SettingsDTO,
    result: ScreeningResult,
    daily_signal_count: int,
) -> str:
    """Возвращает текст уведмолени в формате дерева."""
    _HEADER = (
        "┌ {screener_name} #{symbol}\n├ 💱 <a href='{link_ex}'>{exchange} {market_type}</a>\n|"
    )
    _FOOTER = """
    ├ 📊 Vol 24h: {daily_volume}$
    ├ 🏷️ Prc 24h: {daily_price}
    ├ 🔔 Sig 24h: {daily_signal_count}
    └ 🔗 <a href='{link_cg}'>CoinGlass</a>; <a href='{link_tv}'>TradingView</a>
    """
    normalized_symbol = normalize_symbol(symbol)
    link_tv = generate_tv_link(exchange, market_type, normalized_symbol)
    link_cg = generate_cg_link(exchange, market_type, normalized_symbol)
    link_ex = generate_ex_link(exchange, market_type, normalized_symbol)

    if settings.oi_status:
        if settings.oi_min_change_pct is not None and result.oi_change_pct is not None:
            oi_main = _fmt_pct(result.oi_change_pct)
        elif settings.oi_min_change_usd is not None and result.oi_change_usdt is not None:
            oi_main = _fmt_dollars(result.oi_change_usdt)
        else:
            oi_main = _fmt_pct(result.oi_change_pct) if result.oi_change_pct is not None else _fmt_dollars(result.oi_change_usdt)  # type: ignore
        oi_block = f"\n├ OI: {oi_main}\n| └ {_fmt_coins(result.oi_start_value)} ⭢ {_fmt_coins(result.oi_final_value)}\n|"  # type: ignore
    else:
        oi_block = None

    if settings.pd_status:
        pd_block = f"\n├ PD: {_fmt_pct(result.pd_price_change_pct)}\n| └ {result.pd_start_price}$ ⭢ {result.pd_final_price}$\n|" #type: ignore
    else:
        pd_block = None

    if settings.vl_status:
        vl_block = f"\n├ VL: {_fmt_multiplier(result.vl_multiplier)}\n|" #type: ignore
    else:
        vl_block = None

    if settings.fr_status:
        fr_block = f"\n├ FR: {result.funding_rate:.4}%\n|"
    else:
        fr_block = None

    if settings.lq_status:
        lq_block = f"\n├ LQ: {_fmt_dollars(result.lq_amount_usdt)}\n|" #type: ignore
    else:
        lq_block = None

    header = _HEADER.format_map(
        dict(
            screener_name=settings.name,
            symbol=symbol,
            link_ex=link_ex,
            exchange=exchange.value.capitalize(),
            market_type=market_type.value.capitalize(),
        )
    )

    footer = _FOOTER.format_map(
        dict(
            daily_volume=make_humanreadable(result.daily_volume),
            daily_price=str(round(result.daily_price, 2)) + "%",
            link_cg=link_cg,
            link_tv=link_tv,
            daily_signal_count=daily_signal_count,
        )
    )

    text = ""
    for part in [header, pd_block, oi_block, vl_block, fr_block, lq_block, footer]:
        if part:
            text += part
    return text


def _generate_default_type_text(
    symbol: str,
    exchange: Exchange,
    market_type: MarketType,
    settings: SettingsDTO,
    result: ScreeningResult,
    daily_signal_count: int,
) -> str:
    """Возвращает текст уведмоления в стандартном формате."""
    _HEADER = "<code>{symbol}</code>"
    _METRICS_HEADER = "📊 Текущие данные:"
    _FOOTER = "🔗 {ex_link} | {tv_link} | {cg_link}"
    normalized_symbol = normalize_symbol(symbol)
    link_ex = generate_ex_link(exchange, market_type, normalized_symbol)
    link_tv = generate_tv_link(exchange, market_type, normalized_symbol)
    link_cg = generate_cg_link(exchange, market_type, normalized_symbol)

    screener_name = settings.name or ""
    cmc_rank = get_cmc_rank_for_symbol(symbol)
    rank_txt = f"#{cmc_rank}" if cmc_rank is not None else ""
    if daily_signal_count == 1:
        header = f"<code>{symbol}</code> {rank_txt} 🔔\n{screener_name}"
    else:
        header = f"<code>{symbol}</code> {rank_txt}\n{screener_name}"

    metrics_lines = [
        f"⦁ Объем (24ч): {make_humanreadable(result.daily_volume)}$",
        #f"⦁ Рейтинг CMC: #{cmc_rank}" if cmc_rank is not None else "⦁ Рейтинг CMC: N/A",
        f"⦁ Фандинг: {result.funding_rate:.4f}%",
        f"⦁ Изменение цены (24ч): {result.daily_price:.2f}%",
        f"⦁ Последняя цена: {_fmt_dollars(result.last_price)}",
        f"⦁ Сигналов за 24ч: {daily_signal_count}",
    ]

    footer = _FOOTER.format_map(
        dict(
            ex_link=f"<a href='{link_ex}'>{exchange.value.capitalize()}</a>",
            tv_link=f"<a href='{link_tv}'>TradingView</a>",
            cg_link=f"<a href='{link_cg}'>CoinGlass</a>",
        )
    )

    parts: list[str] = [header]

    parts.append("\n".join([_METRICS_HEADER, *metrics_lines]))
    parts.append(footer)

    return "\n\n".join(parts)

# todo вставить секунды
def generate_text(
symbol: str,
exchange: Exchange,
market_type: MarketType,
settings: SettingsDTO,
result: ScreeningResult,
daily_signal_count: int,
) -> str:
    """Собирает итоговый текст сигнала для Telegram."""
    if settings.text_template_type == TextTemplateType.TREE:
        return _generate_tree_type_text(
            symbol, exchange, market_type, settings, result, daily_signal_count
        )
    elif settings.text_template_type == TextTemplateType.DEFAULT:
        return _generate_default_type_text(
            symbol, exchange, market_type, settings, result, daily_signal_count
        )
    else:
        raise ValueError(f"Unknown text template type: {settings.text_template_type}")
