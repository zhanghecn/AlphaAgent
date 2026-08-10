import { PanelHead } from "@/components/PanelHead";

/** 低吸规则说明：当前超跌反弹与趋势回踩的可执行口径。 */
export function LowSuctionGuideView() {
  return (
    <section aria-label="低吸规则说明" className="text-sm">
      <PanelHead no="01" zh="上升趋势低吸规则（v4）" en="TREND PULLBACK" note="主升浪中的安静回踩" />
      <div className="space-y-3 border-b px-3 py-4 sm:px-4">
        <div>
          <div className="mb-1 font-semibold">前置结构（硬门槛）</div>
          <ul className="ml-4 list-disc space-y-0.5 text-muted-foreground">
            <li>多头排列：MA5 &gt; MA10 &gt; MA20 &gt; MA30（三线），且 MA10/MA20/MA30 全部向上 —— 不硬性要求 MA60，适配长期下跌刚转势、MA60 仍在上方的情况</li>
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
            <li>振幅安静度(语境) 22 + 趋势年龄 14（6-10 天满分）+ 回踩线别 14（MA5=14 / MA10=9）+ 换手率梯度 12（&lt;3% 满分，不门禁）</li>
            <li>连续小 K 线 14（≥5 根满分）+ 昨日已跌 8 + 收盘位置 8 + 趋势老嫩 5 + 当日缩量 3</li>
            <li>语境调节：转势票(MA60&gt;MA30) 中等振幅 5-8% 反而满分（反弹启动特征 +0.018%）；成熟票需极安静 &lt;3%（同区间 -0.583%）</li>
          </ul>
        </div>
      </div>

      <PanelHead no="02" zh="超跌反弹低吸规则（v2.6）" en="OVERSOLD REBOUND" note="先认形态，再在同日候选中排序" />
      <div className="space-y-3 border-b px-3 py-4 sm:px-4">
        <div>
          <div className="mb-1 font-semibold">先准入，再评分</div>
          <ul className="ml-4 list-disc space-y-0.5 text-muted-foreground">
            <li>命名研究形态决定是否进入超跌池；分数只决定同日、同族候选的先后。没有命中形态的股票，不会因其他分项高分进入列表。</li>
            <li>超跌只覆盖长期空头走向多头的过渡段。MA10&gt;MA20&gt;MA30 已稳定成立的股票，转入趋势低吸，不和超跌候选混排。</li>
          </ul>
        </div>
        <div>
          <div className="mb-1 font-semibold">形态一：三线收敛阳线包裹</div>
          <ul className="ml-4 list-disc space-y-0.5 text-muted-foreground">
            <li>长期空头后，MA10 已开始越过 MA20；MA10、MA20、MA30 尚未跑散，阳线实体把三条线包住。</li>
            <li>低点要真正贴到均线附近，且信号日前的量能已经缩下来。均线隔得很开、靠大阳线强行跨过的“包裹”不算。</li>
          </ul>
        </div>
        <div>
          <div className="mb-1 font-semibold">形态二：P1 分段支撑</div>
          <ul className="ml-4 list-disc space-y-0.5 text-muted-foreground">
            <li>MA10 已上穿 MA20、仍在 MA30 下方；价格回踩 MA10 获支撑。随后 MA10 与 MA30 的距离继续缩小，量能呈阶梯式收缩。</li>
            <li>这是“先过 MA20、再准备过 MA30”的地基，而不是均线已经拉开后的追涨。传智教育 7-22、7-24 属于这条路径。</li>
          </ul>
        </div>
        <div>
          <div className="mb-1 font-semibold">形态三：过 MA30 后的回踩修复</div>
          <ul className="ml-4 list-disc space-y-0.5 text-muted-foreground">
            <li>MA10 曾经上穿 MA30，随后价格深回撤到 MA30 附近；回撤段先缩量，信号日前后重新出现量能恢复。</li>
            <li>它仍是超跌转势过程中的回踩，不把所有“MA10 已在 MA30 上方”的股票都当成超跌候选。</li>
          </ul>
        </div>
        <div>
          <div className="mb-1 font-semibold">排除与排序</div>
          <ul className="ml-4 list-disc space-y-0.5 text-muted-foreground">
            <li>信号日触及涨停、低点没有真实均线支撑，或 MA10 已远离 MA30 且没有回踩修复结构，均不作为该阶段的低吸形态。</li>
            <li>基础排序看均线支撑、空头持续时间、K 线是否安静、收盘是否脱离支撑、以及量能是否有序收缩。换手率 ≥8% 不改变规则命中，但诊断分封顶 39，避免高换手派发占据前列。</li>
            <li><span className="text-foreground">P1 的活跃承接加分：</span>仅当 P1 已命中且换手率在 1.5%~8% 时加 8 分。它奖励“缩量但仍有承接”，不让无成交的缩量地基排在前面；不满足 P1 的股票不会得到这 8 分。</li>
            <li>超跌诊断总分最高 140，用于排序而非预测收益概率；分数跨版本不可直接比较。</li>
          </ul>
        </div>
      </div>

      <PanelHead no="03" zh="口径与边界" en="CONVENTION" note="诚实边界，不外推" />
      <div className="space-y-2 px-3 py-4 text-muted-foreground sm:px-4">
        <ul className="ml-4 list-disc space-y-0.5">
          <li>数据口径：raw_unadjusted 不复权日线（探索级，除权日有已知污染）；D+1 收盘到收盘收益，未扣费</li>
          <li>回测执行：每日趋势/超跌各取综合分最高的前 5 只，单票固定 10%，不足 10 只的槽位留现金；具体结果以「回测」页最新物化报告为准</li>
          <li>回测解读：只看当前评分版本、固定规则和固定前五排序的结果；页面分数段用于复核，不构成收益承诺</li>
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
