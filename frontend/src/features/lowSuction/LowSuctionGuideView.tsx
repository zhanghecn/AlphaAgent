import { PanelHead } from "@/components/PanelHead";

/** 低吸规则说明：v3 超跌反弹 + v4 趋势回踩两族因子规则的完整口径。 */
export function LowSuctionGuideView() {
  return (
    <section aria-label="低吸规则说明" className="text-sm">
      <PanelHead no="01" zh="上升趋势低吸规则（v4）" en="TREND PULLBACK" note="主升浪中的安静回踩" />
      <div className="space-y-3 border-b px-3 py-4 sm:px-4">
        <div>
          <div className="mb-1 font-semibold">前置结构（硬门槛）</div>
          <ul className="ml-4 list-disc space-y-0.5 text-muted-foreground">
            <li>完全多头排列：MA5 &gt; MA10 &gt; MA20 &gt; MA30 &gt; MA60，且各均线全部向上</li>
            <li>D 日低点回踩 MA5（强趋势）或 MA10（MA5 不规律时）—— 影线触碰区间 -4% ~ +1.5%，收盘不破 -1.5%</li>
          </ul>
        </div>
        <div>
          <div className="mb-1 font-semibold">基础形态：安静小 K 线（candle_quiet）</div>
          <ul className="ml-4 list-disc space-y-0.5 text-muted-foreground">
            <li>D 日振幅 ≤ 5%（(最高-最低)/前收）—— 小阴小阳的下影线低点才算回踩，嘈杂 K 线的影线是噪音</li>
            <li>依据：全量 811 日最单调变量 —— 振幅 &lt;3% 组 +0.013% → ≥10% 组 <span className="text-emerald-600">-0.734%</span></li>
          </ul>
        </div>
        <div>
          <div className="mb-1 font-semibold">否决 1：首阴追高（trend_first_crack_chase）</div>
          <ul className="ml-4 list-disc space-y-0.5 text-muted-foreground">
            <li>振幅 &gt;5% 且收盘没回到 MA5（距 MA5 ≥ 0）且<span className="text-foreground">昨日仍在涨</span> —— 大涨后的第一根分歧巨震，追高买首阴</li>
            <li>昨日已跌 = 分歧已开始释放，才算低吸语境；全量单调：昨日 &lt;-5% 组 -0.058% → 昨日 ≥5% 组 <span className="text-emerald-600">-0.867%</span></li>
          </ul>
        </div>
        <div>
          <div className="mb-1 font-semibold">否决 2：趋势过伸（trend_overextended）</div>
          <ul className="ml-4 list-disc space-y-0.5 text-muted-foreground">
            <li>当前 M5-M10 距离 ≥ 本段多头趋势内此前每次回踩日距离中位数 + 2 个百分点 —— 相对本段自己的回踩签名判断趋势老嫩，不用绝对阈值</li>
            <li>全区间单调：超额 &lt;0 组 -0.134% → ≥6 组 <span className="text-emerald-600">-1.049%</span></li>
          </ul>
        </div>
        <div>
          <div className="mb-1 font-semibold">落地规则与验证</div>
          <ul className="ml-4 list-disc space-y-0.5 text-muted-foreground">
            <li><span className="text-foreground">安静小K线回踩（v4_quiet）</span>：多头排列 + 安静 K 线低点回踩 MA5/MA10 + 非过伸 —— 最纯形态</li>
            <li><span className="text-foreground">真实回踩（v4_authentic）</span>：多头排列 + 低点回踩 + 非首阴追高 + 非过伸 —— 通用形态</li>
            <li>验证：6/6 趋势坏样本全部命中否决；8/8 个人案例零误伤；官方案例门禁 15/15；全量均值 -0.008% 打赢全部同族基线（-0.092~-0.120）</li>
          </ul>
        </div>
        <div>
          <div className="mb-1 font-semibold">综合评分构成（0-100）</div>
          <ul className="ml-4 list-disc space-y-0.5 text-muted-foreground">
            <li>安静小 K 线 20 + 回踩线别 15（MA5=15 / MA10=8）+ 距离超额梯度 20（&lt;0 满分）+ 昨日已跌 10 + 收盘位置 10（收在 MA5 下方满分）</li>
            <li>连续小 K 线 20（≥4 根满分 / 3 根 12 / 2 根 6）+ 当日缩量 5</li>
          </ul>
        </div>
      </div>

      <PanelHead no="02" zh="超跌反弹低吸规则（v3）" en="OVERSOLD REBOUND" note="长期空头后的上穿过程回踩" />
      <div className="space-y-3 border-b px-3 py-4 sm:px-4">
        <div>
          <div className="mb-1 font-semibold">前置结构（硬门槛）</div>
          <ul className="ml-4 list-disc space-y-0.5 text-muted-foreground">
            <li>长期空头排列后，MA10 处于分阶段上穿过程：MA10 先上穿 MA20 / 双上穿 / MA5-MA10 联合上攻 / MA10 已上穿 MA30（15 日内）之一成立</li>
          </ul>
        </div>
        <div>
          <div className="mb-1 font-semibold">核心 1：低点获均线实际支撑</div>
          <ul className="ml-4 list-disc space-y-0.5 text-muted-foreground">
            <li>D 日低点在 MA10/MA20/MA30 获实际支撑且收盘有反应 —— 缩量贴死低点 = 接飞刀，必须看到收盘脱离</li>
          </ul>
        </div>
        <div>
          <div className="mb-1 font-semibold">核心 2：换手率门禁（唯一全段单调变量）</div>
          <ul className="ml-4 list-disc space-y-0.5 text-muted-foreground">
            <li>换手率 &lt;3% 最优（-0.07% 组）、&lt;8% 为门禁线；≥8% 组 -0.53% —— 高换手 = 派发不是吸筹</li>
          </ul>
        </div>
        <div>
          <div className="mb-1 font-semibold">核心 3：崩盘日紧凑反弹</div>
          <ul className="ml-4 list-disc space-y-0.5 text-muted-foreground">
            <li>MA10 上穿后回贴 MA30 的崩盘日：换手 &lt;3% 且收盘脱离低点 0.3~1.5% —— 研究中唯一全时间段为正的形态</li>
          </ul>
        </div>
        <div>
          <div className="mb-1 font-semibold">综合评分构成（0-100）</div>
          <ul className="ml-4 list-disc space-y-0.5 text-muted-foreground">
            <li>低点支撑 20 + 换手率梯度 20（&lt;3% 满分）+ 崩盘脱离低点 15（紧凑满分）+ 上穿过程结构 15 + 收盘支撑反应 10 + 梯形缩量 10 + 安静 K 线 5 + 连续小 K 线 5</li>
          </ul>
        </div>
      </div>

      <PanelHead no="03" zh="口径与边界" en="CONVENTION" note="诚实边界，不外推" />
      <div className="space-y-2 px-3 py-4 text-muted-foreground sm:px-4">
        <ul className="ml-4 list-disc space-y-0.5">
          <li>数据口径：raw_unadjusted 不复权日线（探索级，除权日有已知污染）；D+1 收盘到收盘收益，未扣费</li>
          <li>回测结论（748 交易日）：每日综合分最高的趋势 1 只 + 超跌 1 只两仓模拟，三年复利 +98.6%、日胜率 50.5%、日均 +0.10%、最大回撤 -12.6%（趋势单仓 +123.0% / 超跌单仓 +63.2%）</li>
          <li>分数段：超跌 60-79 与 80-89 区间 validation+holdout 双段为正（回测页「推荐」标记同口径）；趋势族人口均值仅打平，超额集中在每日最高分口袋</li>
          <li>并列决胜：超跌顶分并列率超九成 —— 并列时按连续小 K 线数更多、换手率更低决胜（均为全量验证的单调方向），回测与实时推荐同一决胜键</li>
          <li>行情主导一切：两族人口均值仅接近打平，本产品按综合分排序取最高，不做全池买入</li>
          <li>实时推荐：交易日内每 30 分钟用现货快照合成当日虚拟 K 线重算（未定型），收盘后以日线同步确认为准；实时组不含 ST 股</li>
        </ul>
        <div className="rounded border border-amber-500/40 bg-amber-500/5 p-3 text-xs text-amber-600">
          ⚠️ 全部内容为历史回测与研究结论，非投资建议；样本外有效性不保证，极端行情下 D+1 仍可能大幅亏损。
        </div>
      </div>
    </section>
  );
}
