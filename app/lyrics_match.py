# -*- coding: utf-8 -*-
"""歌词匹配的纯文本层（v3.0.5）：归一化 / 分词 / 相似度 / 权重。

为什么单独开一个模块：`lyrics_online` 已经 740 行（HTTP + 查询计划 + 缓存 +
打分全在一起），再往里面塞繁简映射表和多语言分词就彻底读不动了。这里只放
**没有网络、没有 Qt、纯函数**的东西，可以完全离线单测；`lyrics_online` 负责
把 `LyricHit` 套上这些信号。

## 三层设计

1. **归一化**（`fold` / `normalize` / `words`）
   NFKC（全角→半角、兼容字符展开）→ 拆变音符号（`Beyoncé` → `Beyonce`）→
   小写 → 繁简归并 → 去标点。全角字母、`Ⅰ`、`①`、`ﬁ` 这类兼容字符由 NFKC
   一并抹平，不必再手写全角映射。
2. **分词**（`tokens`）
   按文字系统切：汉字 / 假名 / 谚文 → **字符 bigram**（不装分词器也能捕捉语序），
   拉丁 / 西里尔 → **词级** token。这是「分语言适配」的核心：中文没有空格，
   按词切需要词典，按 bigram 切既无依赖又够用；英文按词切才不会被长词淹没。
3. **相似度**（`similarity`）
   `max(字符级 SequenceMatcher 比例, token 级 Dice 系数)`：前者对拼写差异
   （大小写、空格、错一个字）敏感，后者对词序调整更宽容。装了 `rapidfuzz`
   就用它的 `normalized_similarity`（同为 0~1、更快），没装退回标准库——
   **不引入硬依赖**（v3.0.5 决策：标准库为主，rapidfuzz 可选）。

## 为什么「繁简归并」不需要一张正确的简繁对照表

匹配只关心「两边的写法是否落到同一个规范形」，不关心规范形是简体还是繁体。
表里写成「繁体 简体」只是为了可读性；即使个别字的映射方向写反了，只要两个
变体映射到同一个字符，匹配结果完全一样。这让表可以放心只收高频字，不必为了
完整性引入 `opencc`（几十 MB 词典）。`test_all_pairs_are_two_chars` 会把
手写表里的错别字（长度不是 2）直接抓出来。
"""
from __future__ import annotations

import difflib
import re
import unicodedata
from dataclasses import dataclass, field

# rapidfuzz 是**可选加速**，不是依赖。装在就快一点，没装行为完全一致。
try:                                     # pragma: no cover - 环境相关
    from rapidfuzz.distance import Levenshtein as _RapidLevenshtein
except Exception:                        # noqa: BLE001  任何导入问题都退标准库
    _RapidLevenshtein = None

HAS_RAPIDFUZZ = _RapidLevenshtein is not None


# ========== 一、标签清洗（从 lyrics_online 迁来，v3.0.5） ==========
#
# 真实曲库的脏标签是匹配失败的头号原因。清洗的原则是「只删明确的噪声」：
# 括号里出现 live/remaster/伴奏/主题曲 这类词才删，不含噪声词的括号保留
# （有些歌名本身带括号）。

_NOISE_WORDS = (
    # 英文
    "live", "remaster", "version", "ver.", "edit", "mix", "remix", "re-record",
    "feat", "ft.", "featuring", "cover", "demo", "acoustic", "mono", "stereo",
    "explicit", "clean", "instrumental", "karaoke", "ost", "soundtrack", "theme",
    "deluxe", "bonus", "single", "radio", "extended", "sped up", "slowed", "reverb",
    "live at", "mv",
    # 中文
    "现场", "演唱会", "伴奏", "纯音乐", "翻唱", "女声", "男声", "高音质", "无损",
    "版", "主题曲", "片头曲", "片尾曲", "插曲", "电视剧", "电影", "动画", "游戏",
    "重置", "重制", "混音", "配乐", "官方", "完整版", "超清", "原唱", "合唱", "组曲",
    "国语", "粤语", "日语", "闽南语",
)

_BRACKET_GROUP = re.compile(r"[\(\[]([^\)\]]*)[\)\]]")
# 前导音轨号，两种形态分开写：
#   ① `[07] 歌名`、`(07) 歌名`——号码带括号时本身就是音轨号的强信号，不必再要求分隔符；
#   ② `01. 歌名`、`01 - 歌名`、`1、歌名`——裸号码必须跟分隔符，
#      否则 Taylor Swift 的《22》这种纯数字歌名会被一起吃掉。
_LEADING_INDEX = re.compile(r"^\s*(?:[\[\(]\d{1,3}[\]\)]\s*|\d{1,3}\s*[.\-、:：_]\s*)")
# 标题里的 `feat. X` 尾巴整段砍掉（艺人字段另外处理，那里是切分而不是砍掉）。
_FEAT_TAIL = re.compile(r"\s*(?:feat\.?|ft\.?|featuring)\s+.*$", re.IGNORECASE)
# 多艺人切分：只认这些分隔符。**不含 `&` 和 `,`**——
# `Simon & Garfunkel`、`Earth, Wind & Fire` 是单一艺人名，切了反而搜不到。
_ARTIST_SPLIT = re.compile(
    r"\s*(?:[;/／、|]|\bfeat\.?\b|\bft\.?\b|\bfeaturing\b)\s*", re.IGNORECASE)
# 「艺人 - 曲名」的分隔符：必须是**两边都有空格**的破折号。
# 不能更宽松——`Jay-Z - 99 Problems` 只在中间那个破折号处切，
# 切 `Jay-Z` 里的连字符会把歌名碎成一堆。
_TITLE_SEP = re.compile(r"\s+[-\u2013\u2014\u2015]\s+")
# 有些平台把「曲名 / 艺人」并排写（`打上花火 / DAOKO×米津玄師`）。
# 只认**两边带空格**的斜杠：`AC/DC` 这种不带空格的绝不能切。
_TITLE_SLASH = re.compile(r"\s+/\s+")
# 没有空格的 `艺人-曲名` 用一个受限正则兜：左段不超过 30 字、不含数字开头。
_TIGHT_PREFIX = re.compile(r"^([^\-\u2013\u2014\u2015]{1,30})[-\u2013\u2014\u2015]+(.+)$")


def to_halfwidth(text: str) -> str:
    """全角 ASCII（U+FF01..FF5E）与全角空格转半角。

    v3.0.5 起 `fold()` 里的 NFKC 已经覆盖这件事，这个函数保留是为了
    不破坏既有调用方（`lookup_plan` 与若干测试仍在用）。
    """
    out = []
    for ch in text or "":
        code = ord(ch)
        if code == 0x3000:
            out.append(" ")
        elif 0xFF01 <= code <= 0xFF5E:
            out.append(chr(code - 0xFEE0))
        else:
            out.append(ch)
    return "".join(out)


def _strip_noise_groups(text: str) -> str:
    """删掉「含噪声词」的括号组；不含噪声词的括号原样留着。

    v3.0.5 增补：**纯数字括号**也算版次标记（`夜曲 (2005)`、
    `Bohemian Rhapsody (2011)`）。这类括号是最常见的「同名不同版本」
    来源，而歌名本身极少是纯数字塞在括号里。
    """
    def repl(match: re.Match) -> str:
        inner = match.group(1).strip()
        if not inner:
            return ""                       # 空括号 `()` 也删
        if inner.isdigit():
            return ""                       # 纯数字 = 年份/版次
        lowered = inner.lower()
        return "" if any(word in lowered for word in _NOISE_WORDS) else match.group(0)

    previous = None
    while previous != text:                 # 循环处理嵌套/连续括号组
        previous = text
        text = _BRACKET_GROUP.sub(repl, text)
    return text


def _strip_noise_tail(text: str) -> str:
    """砍掉 `歌名 - Remastered 2011` 这种「破折号 + 噪声后缀」的尾巴。

    只处理最后一段、且该段含噪声词，避免误伤 `Jay-Z - 99 Problems` 这类
    破折号本来就在歌名里的情况（`99 problems` 不含噪声词，原样保留）。
    """
    parts = text.split(" - ")
    if len(parts) > 1 and any(word in parts[-1].lower() for word in _NOISE_WORDS):
        return " - ".join(parts[:-1])
    return text


def clean_title(title: str) -> str:
    """把标题洗成「适合拿去检索」的样子；洗空了就退回原文，绝不返回空串。"""
    original = to_halfwidth(title or "").strip()
    if not original:
        return ""
    text = _strip_noise_groups(original)
    text = _FEAT_TAIL.sub("", text)
    text = _strip_noise_tail(text)
    text = _LEADING_INDEX.sub("", text)
    text = re.sub(r"\s{2,}", " ", text).strip(" -_·.")
    return text or original


def clean_artist(artist: str) -> str:
    """多艺人取主艺人；切不动就原样返回。"""
    original = to_halfwidth(artist or "").strip()
    if not original:
        return ""
    primary = _ARTIST_SPLIT.split(original)[0].strip(" -_·,")
    return primary or original


# ========== 二、繁简归并表 ==========
#
# 只收「流行歌词标题里高频」的字，约 500 组。不是完整的简繁对照表——
# 匹配只需要「变体落到同一个形」，见模块开头的说明。
# 维护提示：每组必须是**两个字**，`_build_t2s()` 会跳过长度不对的项，
# `test_all_pairs_are_two_chars` 会把错别字钉死在测试里。
_T2S_PAIRS = """
愛爱 礙碍 罷罢 擺摆 敗败 頒颁 辦办 綁绑 幫帮 寶宝 報报 備备 筆笔 畢毕 閉闭
邊边 編编 變变 標标 錶表 別别 賓宾 補补 財财 採采 參参 殘残 慘惨 燦灿 倉仓
側侧 層层 產产 場场 嘗尝 長长 償偿 腸肠 暢畅 車车 徹彻 塵尘 陳陈 稱称 誠诚
遲迟 齒齿 沖冲 蟲虫 寵宠 籌筹 醜丑 處处 觸触 傳传 創创 純纯 詞词 聰聪 從从
湊凑 錯错 達达 帶带 貸贷 擔担 單单 膽胆 彈弹 當当 擋挡 黨党 檔档 導导 島岛
盜盗 燈灯 敵敌 遞递 點点 墊垫 電电 釣钓 調调 頂顶 訂订 東东 動动 凍冻 鬥斗
獨独 讀讀 賭赌 斷断 隊队 對对 頓顿 奪夺 鵝鹅 額额 惡恶 餓餓 兒儿 爾尔 發发
罰罚 範范 飯饭 訪访 飛飞 廢废 費费 紛纷 墳坟 奮奋 憤愤 豐丰 風风 瘋疯 縫缝
諷讽 鳳凤 膚肤 撫抚 輔辅 賦赋 復复 負负 婦妇 該该 蓋盖 幹干 趕赶 剛刚 鋼钢
綱纲 崗岗 擱搁 鴿鸽 閣阁 個个 給给 宮宫 鞏巩 貢贡 溝沟 鉤钩 構构 購购 夠够
顧顾 關关 觀观 館馆 慣惯 貫贯 廣广 規规 龜龟 歸归 軌轨 詭诡 櫃柜 貴贵 鍋锅
國国 過过 駭骇 韓韩 漢汉 號号 鶴鹤 賀贺 橫横 轟轰 紅红 後后 壺壶 護护 滬沪
戶户 華华 畫画 劃划 話话 懷怀 壞坏 歡欢 環环 還还 緩缓 換换 喚唤 黃黄 謊谎
揮挥 輝辉 毀毁 賄贿 會会 彙汇 諱讳 繪绘 葷荤 渾浑 夥伙 獲获 貨货 禍祸 擊击
機机 積积 饑饥 譏讥 雞鸡 績绩 極极 輯辑 級级 擠挤 幾几 劑剂 濟济 計计 記记
際际 繼继 紀纪 夾夹 頰颊 價价 駕驾 殲歼 監监 堅坚 間间 艱艰 繭茧 檢检 鹼碱
揀拣 撿捡 簡简 儉俭 減减 薦荐 鑒鉴 踐践 賤贱 見见 鍵键 艦舰 劍剑 漸渐 濺溅
將将 漿浆 蔣蒋 槳桨 獎奖 講讲 醬酱 膠胶 澆浇 驕骄 嬌娇 攪搅 鉸铰 矯矫 僥侥
腳脚 餃饺 繳缴 絞绞 轎轿 較较 階阶 節节 潔洁 結结 誡诫 屆届 緊紧 錦锦 僅仅
謹谨 進进 晉晋 盡尽 勁劲 荊荆 莖茎 鯨鲸 驚惊 經经 頸颈 靜静 鏡镜 徑径 競竞
淨净 糾纠 舊旧 駒驹 舉举 據据 鋸锯 懼惧 劇剧 絹绢 傑杰 覺觉 決决 訣诀 絕绝
軍军 駿骏 開开 凱凯 顆颗 殼壳 課课 墾垦 懇恳 庫库 褲裤 誇夸 塊块 寬宽 礦矿
曠旷 況况 虧亏 窺窥 饋馈 潰溃 擴扩 闊阔 蠟蜡 臘腊 萊莱 來来 賴赖 藍蓝 欄栏
攔拦 籃篮 闌阑 蘭兰 瀾澜 攬揽 覽览 懶懒 纜缆 爛烂 濫滥 撈捞 勞劳 澇涝 樂乐
壘垒 類类 淚泪 籬篱 離离 裡里 裏里 鯉鲤 禮礼 麗丽 厲厉 勵励 歷历 曆历 瀝沥
隸隶 倆俩 聯联 蓮莲 連连 鐮镰 憐怜 漣涟 簾帘 斂敛 臉脸 鏈链 戀恋 煉炼 練练
糧粮 涼凉 兩两 輛辆 諒谅 療疗 遼辽 獵猎 臨临 鄰邻 鱗鳞 凜凛 賃赁 靈灵 嶺岭
領领 劉刘 龍龙 聾聋 嚨咙 籠笼 壟垄 攏拢 樓楼 婁娄 摟搂 蘆芦 盧卢 顱颅 廬庐
爐炉 擄掳 鹵卤 虜虏 魯鲁 賂赂 祿禄 錄录 陸陆 驢驴 呂吕 鋁铝 侶侣 屢屡 縷缕
慮虑 濾滤 綠绿 巒峦 亂乱 輪轮 倫伦 侖仑 淪沦 綸纶 論论 蘿萝 羅罗 邏逻 鑼锣
騾骡 駱骆 絡络 媽妈 瑪玛 碼码 螞蚂 馬马 罵骂 嗎吗 買买 麥麦 賣卖 邁迈 脈脉
瞞瞒 饅馒 蠻蛮 滿满 貓猫 貿贸 麼么 沒没 門门 悶闷 們们 夢梦 謎谜 彌弥 覓觅
綿绵 緬缅 廟庙 滅灭 憫悯 閩闽 鳴鸣 銘铭 謬谬 謀谋 畝亩 納纳 難难 撓挠 腦脑
惱恼 鬧闹 內内 擬拟 膩腻 釀酿 鳥鸟 聶聂 鎳镍 檸柠 獰狞 寧宁 擰拧 濘泞 鈕钮
紐纽 膿脓 濃浓 農农 瘧疟 諾诺 歐欧 鷗鸥 毆殴 嘔呕 盤盘 龐庞 拋抛 賠赔 噴喷
鵬鹏 騙骗 飄飘 頻频 貧贫 蘋苹 憑凭 評评 潑泼 頗颇 撲扑 鋪铺 樸朴 譜谱 棲栖
淒凄 臍脐 齊齐 騎骑 豈岂 啟启 氣气 棄弃 牽牵 鉛铅 遷迁 簽签 謙谦 錢钱 鉗钳
潛潜 淺浅 譴谴 槍枪 嗆呛 牆墙 薔蔷 強强 搶抢 橋桥 喬乔 僑侨 翹翘 竅窍 竊窃
欽钦 親亲 寢寝 輕轻 氫氢 傾倾 頃顷 請请 慶庆 瓊琼 窮穷 趨趋 區区 軀躯 驅驱
權权 勸劝 卻却 鵲鹊 確确 讓让 饒饶 擾扰 繞绕 熱热 韌韧 認认 紉纫 榮荣 絨绒
軟软 銳锐 閏闰 潤润 灑洒 薩萨 鰓鳃 賽赛 傘伞 喪丧 騷骚 掃扫 澀涩 殺杀 紗纱
篩筛 曬晒 刪删 閃闪 陝陕 贍赡 繕缮 傷伤 賞赏 燒烧 紹绍 賒赊 攝摄 懾慑 設设
紳绅 審审 嬸婶 腎肾 滲渗 聲声 繩绳 勝胜 聖圣 師师 蝨虱 獅狮 濕湿 詩诗 屍尸
時时 蝕蚀 實实 識识 駛驶 勢势 適适 釋释 飾饰 視视 試试 壽寿 獸兽 樞枢 輸输
書书 贖赎 屬属 術术 樹树 豎竖 數数 帥帅 雙双 誰谁 稅税 順顺 說说 碩硕 爍烁
絲丝 飼饲 聳耸 慫怂 頌颂 訟讼 誦诵 擻擞 蘇苏 訴诉 肅肃 雖虽 隨随 綏绥 歲岁
孫孙 損损 筍笋 縮缩 瑣琐 鎖锁 臺台 檯台 態态 攤摊 貪贪 癱瘫 灘滩 壇坛 譚谭
談谈 歎叹 湯汤 燙烫 濤涛 討讨 騰腾 謄誊 題题 體体 屜屉 條条 貼贴 鐵铁 廳厅
聽听 銅铜 統统 頭头 禿秃 圖图 塗涂 團团 頹颓 蛻蜕 脫脱 鴕鸵 馱驮 駝驼 橢椭
窪洼 襪袜 彎弯 灣湾 頑顽 萬万 網网 韋韦 違违 圍围 為为 維维 葦苇 偉伟 偽伪
緯纬 謂谓 衛卫 溫温 聞闻 紋纹 穩稳 問问 甕瓮 蝸蜗 渦涡 窩窝 臥卧 嗚呜 烏乌
汙污 誣诬 無无 蕪芜 吳吴 塢坞 霧雾 務务 誤误 錫锡 犧牺 襲袭 習习 戲戏 細细
蝦虾 轄辖 峽峡 俠侠 狹狭 廈厦 嚇吓 鮮鲜 纖纤 鹹咸 賢贤 銜衔 閒闲 顯显 險险
現现 獻献 縣县 餡馅 羨羡 憲宪 線线 廂厢 鑲镶 鄉乡 詳详 響响 項项 蕭萧 囂嚣
銷销 曉晓 嘯啸 蠍蝎 協协 挾挟 攜携 脅胁 諧谐 寫写 瀉泻 謝谢 鋅锌 釁衅 興兴
洶汹 鏽锈 繡绣 虛虚 噓嘘 須须 許许 敘叙 緒绪 續续 軒轩 懸悬 選选 癬癣 絢绚
學学 勳勋 詢询 尋寻 馴驯 訓训 訊讯 遜逊 壓压 鴉鸦 鴨鸭 啞哑 亞亚 訝讶 煙烟
鹽盐 嚴严 顏颜 閻阎 艷艳 厭厌 硯砚 彥彦 諺谚 驗验 鴦鸯 楊杨 揚扬 瘍疡 陽阳
癢痒 養养 樣样 瑤瑶 搖摇 堯尧 遙遥 窯窑 謠谣 藥药 爺爷 頁页 業业 葉叶 醫医
頤颐 遺遗 儀仪 蟻蚁 誼谊 議议 詣诣 譯译 異异 繹绎 蔭荫 陰阴 銀银 飲饮 隱隐
櫻樱 嬰婴 鷹鹰 應应 纓缨 瑩莹 螢萤 營营 熒荧 蠅蝇 贏赢 穎颖 喲哟 擁拥 傭佣
癰痈 踴踊 詠咏 湧涌 優优 憂忧 郵邮 鈾铀 猶犹 遊游 誘诱 與与 嶼屿 語语 籲吁
禦御 獄狱 譽誉 預预 馭驭 鴛鸳 淵渊 轅辕 園园 員员 圓圆 緣缘 遠远 願愿 約约
躍跃 鑰钥 嶽岳 粵粤 悅悦 閱阅 雲云 勻匀 隕陨 運运 蘊蕴 醞酝 暈晕 韻韵 雜杂
災灾 載载 攢攒 暫暂 讚赞 贓赃 髒脏 鑿凿 棗枣 竈灶 責责 擇择 則则 澤泽 賊贼
贈赠 紮扎 鍘铡 閘闸 軋轧 詐诈 齋斋 債债 氈毡 盞盏 斬斩 輾辗 嶄崭 棧栈 戰战
綻绽 張张 漲涨 帳帐 賬账 脹胀 趙赵 蟄蛰 轍辙 這这 貞贞 針针 偵侦 診诊 鎮镇
陣阵 掙挣 睜睁 猙狰 爭争 幀帧 鄭郑 證证 織织 職职 執执 紙纸 摯挚 擲掷 幟帜
質质 滯滞 鐘钟 終终 種种 腫肿 眾众 軸轴 皺皱 晝昼 驟骤 豬猪 諸诸 誅诛 燭烛
矚瞩 囑嘱 貯贮 鑄铸 築筑 駐驻 專专 磚砖 轉转 賺赚 樁桩 莊庄 裝装 妝妆 壯壮
狀状 錐锥 贅赘 墜坠 綴缀 諄谆 準准 濁浊 茲兹 資资 漬渍 蹤踪 綜综 總总 縱纵
鄒邹 詛诅 組组 鑽钻 祕秘 妳你 週周 儘尽 嚮向 藉借 佈布 佔占 倖幸 侷局 甦苏
鉅巨 覈核 於于 麽么 燙烫 麼么 嗎吗 呢呢
"""


def _build_t2s(pairs_text: str) -> dict[str, str]:
    """把「繁简 繁简 …」的空白分隔串解析成映射；长度不对的项直接跳过。"""
    table: dict[str, str] = {}
    for token in pairs_text.split():
        if len(token) != 2:
            continue                     # 手写表的错别字不该让整个匹配崩掉
        table[token[0]] = token[1]
    return table


T2S = _build_t2s(_T2S_PAIRS)


def _to_simplified(text: str) -> str:
    """按表把繁体变体归并到简体形；表里没有的字原样留下。"""
    if not text:
        return ""
    return "".join(T2S.get(ch, ch) for ch in text)


# ========== 三、归一化 ==========


def fold(text: str) -> str:
    """规范化但**保留标点**：NFKC → 拆变音 → 重组合 → 小写 → 繁简归并。

    保留标点是为了让 `words()` 能用标点当词边界；要纯字母数字用 `normalize()`。

    **末尾的 NFC 不能省**：NFKD 会把韩文谚文（`봄`）拆成相容字母（`봄`），
    拆完不重组的话，韩文标题就成了字母串，bigram 全乱、和拼写无关的字符
    也会混进来。拆变音符号只需要「去掉 Mn」，重组负责把谚文接回去。
    """
    if not text:
        return ""
    normalized = unicodedata.normalize("NFKC", text)
    decomposed = unicodedata.normalize("NFKD", normalized)
    stripped = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    recomposed = unicodedata.normalize("NFC", stripped)
    return _to_simplified(recomposed.casefold())


def normalize(text: str) -> str:
    """紧凑形：只留字母数字。同 `_norm` 的语义，但多了 NFKC/拆音/繁简归并。"""
    return "".join(ch for ch in fold(text) if ch.isalnum())


def words(text: str) -> list[str]:
    """词级切分：标点当边界。中文整句会是一个「词」，交给 `tokens()` 再切 bigram。"""
    out: list[str] = []
    buffer: list[str] = []
    for ch in fold(text):
        if ch.isalnum():
            buffer.append(ch)
        elif buffer:
            out.append("".join(buffer))
            buffer.clear()
    if buffer:
        out.append("".join(buffer))
    return out


# 文字系统判定：CJK 按字符 bigram，其余按词。顺序有讲究——假名先于汉字判，
# 否则「打上花火」里的假名会被算进汉字，日文歌被误判成中文。
_HANGUL = ((0xAC00, 0xD7A3), (0x1100, 0x11FF), (0x3130, 0x318F))
_KANA = ((0x3040, 0x30FF), (0x31F0, 0x31FF))
_HAN = ((0x3400, 0x4DBF), (0x4E00, 0x9FFF), (0xF900, 0xFAFF))
_CYRILLIC = ((0x0400, 0x04FF), (0x0500, 0x052F))


def _in_ranges(code: int, ranges) -> bool:
    return any(low <= code <= high for low, high in ranges)


def script_of(ch: str) -> str:
    """单字符的书写系统：han / kana / hangul / cyrillic / latin / other。"""
    code = ord(ch)
    if _in_ranges(code, _HANGUL):
        return "hangul"
    if _in_ranges(code, _KANA):
        return "kana"
    if _in_ranges(code, _HAN):
        return "han"
    if _in_ranges(code, _CYRILLIC):
        return "cyrillic"
    if ch.isalpha() or ch.isdigit():
        return "latin"
    return "other"


# 「按字符切」的书写系统：没有词边界，bigram 才是可靠 unit。
_CJK_SCRIPTS = frozenset({"han", "kana", "hangul"})


def tokens(text: str) -> list[str]:
    """分语言 token：CJK 出字符 bigram（单字退 unigram），其余出整词。

    不装分词器也能吃到语序信息：`晴天`→`{晴天}`、`下雨天`→`{下雨, 雨天}`，
    两者交集为空——这就是「单字歌名不该匹配到更长的歌」在算法上的来源。
    """
    out: list[str] = []
    for word in words(text):
        script = script_of(word[0]) if word else "other"
        if script in _CJK_SCRIPTS:
            if len(word) == 1:
                out.append(word)
            else:
                out.extend(word[i:i + 2] for i in range(len(word) - 1))
        else:
            out.append(word)
    return out


def _char_ratio(a: str, b: str) -> float:
    """字符级相似度 0~1。有 rapidfuzz 用它的，否则用标准库。"""
    if _RapidLevenshtein is not None:      # pragma: no cover - 环境相关
        try:
            return float(_RapidLevenshtein.normalized_similarity(a, b))
        except Exception:                  # noqa: BLE001  任何异常都退标准库
            pass
    # autojunk=False：长串里重复字符多时，默认的自动去重会让比例失真
    return difflib.SequenceMatcher(None, a, b, autojunk=False).ratio()


def _dice(a: list[str], b: list[str]) -> float:
    """token 级 Dice 系数：2|A∩B| / (|A|+|B|)，对词序调整比字符比对宽容。"""
    if not a or not b:
        return 0.0
    set_a, set_b = set(a), set(b)
    if not set_a or not set_b:
        return 0.0
    return 2.0 * len(set_a & set_b) / (len(set_a) + len(set_b))


def similarity(a: str, b: str) -> float:
    """两段文字的相似度 0~1，已做过归一化与分语言分词。

    取两条路的**最大值**而不是加权平均：标题这种短串，只要一条路认出
    「就是同一个」，另一条路分数低并不构成反证（多语言的写法差异正是如此）。
    """
    compact_a, compact_b = normalize(a), normalize(b)
    if not compact_a or not compact_b:
        return 0.0
    if compact_a == compact_b:
        return 1.0
    return max(_char_ratio(compact_a, compact_b),
               _dice(tokens(a), tokens(b)))


def language_of(text: str) -> str:
    """粗判主语言：zh / ja / ko / ru / latin / unknown。

    判据是「各文字系统的字符占比」，不是语言学——
    有假名就是日文（日文必然混汉字，反之不成立）；有谚文就是韩文；
    汉字最多就是中文；西里尔最多是俄语；其余按拉丁算。
    数字与标点不参与判定：`2020` 不该被当成一种语言。
    """
    counts = {"han": 0, "kana": 0, "hangul": 0, "cyrillic": 0, "latin": 0}
    for ch in fold(text):
        if not ch.isalpha():
            continue
        script = script_of(ch)
        if script in counts:
            counts[script] += 1
    if counts["kana"]:
        return "ja"
    if counts["hangul"]:
        return "ko"
    if not any(counts.values()):
        return "unknown"
    primary = max(counts, key=lambda key: counts[key])
    return {"han": "zh", "cyrillic": "ru", "latin": "latin"}.get(primary, "unknown")


def script_set(text: str) -> frozenset[str]:
    """一段文字用到哪些书写系统（只算字母，不算数字标点）。"""
    return frozenset(script_of(ch) for ch in fold(text)
                     if ch.isalpha() and script_of(ch) != "other")


def scripts_disjoint(a: str, b: str) -> bool:
    """两段文字的书写系统是否完全不重叠（`BTS` vs `방탄소년단`）。

    **这是「分语言适配」里最关键的一条兜底规则**。跨书写系统的字符串做字符
    比对必然得 0 分——不是因为「不像」，而是因为根本无从比较。若不区分
    「不相似」和「无法比较」，跨语言的正确候选会被当成「艺人对不上」而
    触发翻唱扣分，越认真越吃亏。调用方据此**不做扣分**，只当这条信号缺失。
    """
    set_a, set_b = script_set(a), script_set(b)
    if not set_a or not set_b:
        return False                       # 信息不足不能算「不相交」
    return not (set_a & set_b)


# ========== 四、候选标题去装饰 ==========

# 「版本类」噪声：命中就要**扣分**（不是删掉就算了）。
# 为什么需要这一条：`晴天` 与 `晴天 (伴奏)` 清洗后完全一样，身份信号打平，
# 谁先出现谁赢——而伴奏/翻唱版本来就不该优先于原版。删噪声解决「搜得到」，
# 负信号解决「选得对」，两件事不能互相替代。
_VERSION_WORDS = (
    "伴奏", "纯音乐", "纯享", "钢琴版", "吉他版", "演奏", "翻唱", "恶搞", "搞笑",
    "karaoke", "instrumental", "off vocal", "offvocal", "backing track",
    "remix", "dj", "cover", "tribute", "live", "现场", "演唱会", "demo",
)
PENALTY_VERSION = -0.4


def _noise_fragments(text: str) -> str:
    """提取被 `clean_title` 删掉的那些片段（版次/噪声括号 + 噪声尾巴）。"""
    fragments: list[str] = []
    for match in _BRACKET_GROUP.finditer(text or ""):
        inner = match.group(1).strip()
        if not inner:
            continue
        if inner.isdigit() or any(word in inner.lower() for word in _NOISE_WORDS):
            fragments.append(inner)
    parts = (text or "").split(" - ")
    if len(parts) > 1 and any(word in parts[-1].lower() for word in _NOISE_WORDS):
        fragments.append(parts[-1])
    return " ".join(fragments)


def version_penalty(title: str) -> float:
    """候选标题带「伴奏/翻唱/Live」这类版次标记时返回负分，否则 0。

    只看**被删掉的那部分**，不看整个标题——`Live and Let Die` 这种歌名里
    本来就含 live 的正常标题不该被误伤（它没有可删的括号，`_noise_fragments`
    返回空）。
    """
    fragments = fold(_noise_fragments(title))
    if not fragments:
        return 0.0
    if any(word in fragments for word in _VERSION_WORDS):
        return PENALTY_VERSION
    return 0.0


def _leads_with(part: str, name: str) -> bool:
    """`part` 是否以 `name` 开头且还有剩余（`DAOKO×米津玄師` 以 `DAOKO` 开头）。"""
    head, needle = normalize(part), normalize(name)
    return bool(head and needle and head != needle and head.startswith(needle))


def strip_artist_prefix(text: str, artist: str) -> str:
    """去掉候选标题里混进来的艺人名：`周杰伦 - 稻香` → `稻香`。

    只在**艺人真能对上**（相似度 ≥ 0.85，或以艺人名开头且还有剩余）且剩下的
    部分非空时才剥。不剥的话，`稻香` 对 `周杰伦 - 稻香` 的字符比例只有 0.5，
    会被当成「不相干的歌」丢掉——这是召回率最常见的一处漏。

    支持三种排布：`艺人 - 曲名`、`曲名 - 艺人`、`曲名 / 艺人`（都要带空格）。
    「以艺人名开头」这条专门给合唱标题用：`打上花火 / DAOKO×米津玄師` 里
    艺人字段只有 `DAOKO`，整段相似度 0.83 卡在阈值下方，但前缀是对得上的。
    """
    title = (text or "").strip()
    name = (artist or "").strip()
    if not title or not name:
        return title
    for sep in (_TITLE_SEP, _TITLE_SLASH):
        parts = sep.split(title)
        if len(parts) < 2:
            continue
        head, tail = parts[0], parts[-1]
        head_ok = similarity(head, name) >= 0.85 or _leads_with(head, name)
        tail_ok = similarity(tail, name) >= 0.85 or _leads_with(tail, name)
        if head_ok and not tail_ok:
            return sep.split(title, maxsplit=1)[1].strip() or title
        if tail_ok and not head_ok:
            return sep.split(title, maxsplit=1)[0].strip() or title
    match = _TIGHT_PREFIX.match(title)
    if match and (similarity(match.group(1), name) >= 0.85
                  or _leads_with(match.group(1), name)):
        return match.group(2).strip() or title
    return title


def prepare_title(text: str, artist: str = "") -> str:
    """把标题变成**用于比对**的形状：去噪声括号/音轨号/feat 尾/艺人前缀。

    查询侧和候选侧都过这一道，保证两边对称——不对称的清洗会让相似度
    莫名其妙地偏低（v3.0.5 之前只洗了查询侧，候选侧的 `(Live)`
    永远是噪声）。
    """
    return strip_artist_prefix(clean_title(text), artist)


# ========== 五、歌词正文指纹（跨源投票用） ==========

_LRC_TAG = re.compile(r"\[[^\]]*\]")


def lyrics_fingerprint(text: str, limit: int = 240) -> str:
    """歌词正文指纹：剥掉时间戳/标记，归一化后取前 `limit` 个字符。

    两个平台给同一首歌的歌词，正文几乎逐字一致（时间轴可能差一点），
    所以指纹相似度 ≥0.85 基本可以认定「同一个源内容」——跨源投票就靠它。
    """
    body = _LRC_TAG.sub(" ", text or "")
    return normalize(body)[:limit]


def same_lyrics(text_a: str, text_b: str, threshold: float = 0.85) -> bool:
    """两段歌词正文是否指向同一内容。任一为空都算不同（避免空串互相投票）。"""
    print_a, print_b = lyrics_fingerprint(text_a), lyrics_fingerprint(text_b)
    if not print_a or not print_b:
        return False
    return similarity(print_a, print_b) >= threshold


# ========== 六、权重与阈值 ==========
#
# 排序（v3.0.5 定稿）：**标题 > 艺人 > 时长 > 专辑**。
# 理由：标题是用户点开这首歌的理由；艺人是防「同名不同曲」的第二道闸；
# 时长是客观物理量但易受前奏/尾奏剪辑影响；专辑信息最脏（各种「精选集」），
# 只作为跨语言时的桥梁。

TITLE_EXACT = 0.95
TITLE_STRONG = 0.85
TITLE_WEAK = 0.70

ARTIST_EXACT = 0.95
ARTIST_STRONG = 0.80
ARTIST_WEAK = 0.55

ALBUM_EXACT = 0.95
ALBUM_STRONG = 0.80

W_TITLE_EXACT = 4.0
W_TITLE_STRONG = 3.2
W_TITLE_WEAK = 1.6
W_ARTIST_EXACT = 2.0
W_ARTIST_STRONG = 1.6
W_ARTIST_WEAK = 0.9
W_DURATION_EXACT = 2.5
W_DURATION_NEAR = 1.6
W_DURATION_FAR = 0.6
W_ALBUM_EXACT = 1.2
W_ALBUM_STRONG = 0.8
W_SYNCED = 0.4
PENALTY_COVER = -1.5

DURATION_EXACT_SEC = 2
DURATION_NEAR_SEC = 5
DURATION_FAR_SEC = 10

CONF_HIGH = "high"
CONF_MEDIUM = "medium"
CONF_LOW = "low"

# 跨源投票：每多一个源给出「同一份歌词」，加分。两个源一致 +0.6，
# 三个源一致 +1.2。上限 1.2——投票是用来**打破平局**的，不该盖过身份信号。
CONSENSUS_BONUS = 0.6
CONSENSUS_BONUS_MAX = 1.2


@dataclass(frozen=True)
class MatchDetail:
    """一次候选打分的过程记录。`reasons` 供日志与评测打印，别用来做判断。"""

    score: float = 0.0
    gate: bool = False
    title_sim: float = 0.0
    artist_sim: float = 0.0
    album_sim: float = 0.0
    duration_diff: float = -1.0          # -1 表示「至少一边没有时长」
    synced: bool = False
    confidence: str = CONF_LOW
    consensus: int = 1
    reasons: tuple[str, ...] = field(default_factory=tuple)


def classify_confidence(title_sim: float, artist_sim: float, album_sim: float,
                        duration_diff: float, gate: bool,
                        artist_known: bool = True,
                        duration_known: bool = True) -> str:
    """把「各信号命中情况」折成置信档位。`duration_diff < 0` 表示时长未知。

    档位只用来回答一个问题：**这条结果敢不敢当成「就是它」**。
    - high：标题强匹配，且另有艺人或时长佐证（两条独立信号）；
    - medium：只有一条信号，但这条信号本身够硬（标题强 / 时长精确且艺人相符 /
      专辑+艺人双向对上）；
    - low：只有弱标题（0.70~0.85）一项，别的什么都没有 —— 这一档最容易
      把「晴天」配到「晴天娃娃」，默认**不接受**（`pick_best(allow_low=False)`）。
    """
    if not gate:
        return CONF_LOW
    duration_ok = duration_known and 0 <= duration_diff <= DURATION_EXACT_SEC
    artist_ok = artist_known and artist_sim >= ARTIST_STRONG

    if title_sim >= TITLE_STRONG and (artist_ok or duration_ok):
        return CONF_HIGH
    if title_sim >= TITLE_STRONG:
        return CONF_MEDIUM                    # 标题很硬，但没别的佐证
    if duration_ok and artist_ok:
        return CONF_HIGH                      # 时长精确 + 艺人相符
    if title_sim >= TITLE_WEAK and artist_ok:
        return CONF_MEDIUM                    # 标题一般但艺人很硬
    if duration_ok:
        return CONF_MEDIUM
    if album_sim >= ALBUM_STRONG and artist_ok:
        return CONF_MEDIUM
    return CONF_LOW
