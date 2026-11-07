from pathlib import Path
import json, html, xml.etree.ElementTree as ET
from PIL import Image, ImageDraw, ImageFont

BASE=Path(__file__).resolve().parents[1]
OUT=BASE/'UI'
OUT.mkdir(parents=True,exist_ok=True)
META=BASE/'process'
META.mkdir(parents=True,exist_ok=True)
W,H,S=1440,1000,2
C={'bg':'#F4F7F8','ink':'#14343F','muted':'#657C84','line':'#DBE5E8','green':'#147D72','mint':'#E6F3EE','white':'#FFFFFF','amber':'#AC6B16','amberbg':'#FFF4DF','red':'#B14E47','redbg':'#FCEDEB','nav':'#102D39','soft':'#EEF3F5','blue':'#356E9C'}
FONT='/System/Library/Fonts/Hiragino Sans GB.ttc'
FONTS={}
PAGES=[]
def font(size):
    if size not in FONTS:FONTS[size]=ImageFont.truetype(FONT,int(size*S))
    return FONTS[size]

class Canvas:
    def __init__(self,num,title,subtitle,nav='商品广场',admin=False):
        self.num,self.title,self.subtitle=num,title,subtitle
        self.im=Image.new('RGB',(W*S,H*S),C['bg']);self.d=ImageDraw.Draw(self.im)
        self.svg=[];self.objs=[];self.req=[];self.description='';self.states=''
        self.rect(0,0,W,H,C['bg']);self.rect(0,0,220,H,C['nav'])
        self.rect(25,30,36,36,C['green'],r=9);self.text(34,35,'循',22,'#FFFFFF')
        self.text(73,28,'校园循物',23,'#FFFFFF');self.text(73,60,'CAMPUS REUSE',10,'#99BBC4')
        self.text(28,112,'管理工作台' if admin else '让闲置继续发光',14,'#99BBC4')
        labels=['商品审核','违规与账号','创建管理员','平台统计','管理日志'] if admin else (['商品广场','登录与注册'] if num==1 else ['商品广场','发布商品','我的商品','我预约的','收到的预约','我的统计','操作历史'])
        for i,label in enumerate(labels):
            yy=165+i*57
            if label==nav:self.rect(16,yy-8,188,44,'#224A55',r=8);self.rect(16,yy-2,4,32,'#6ED1B7',r=2)
            self.rect(30,yy+5,13,13,'#6ED1B7' if label==nav else '#718F98',r=3)
            self.text(57,yy,label,16,'#FFFFFF' if label==nav else '#AAC1C8')
        self.line(25,884,195,884,'#31505A')
        self.text(28,907,'管理员 · 示例账号' if admin else ('访客 · 尚未登录' if num==1 else '普通用户 · 示例账号'),13,'#AAC1C8')
        self.text(28,944,'返回商品广场' if num==1 else '退出登录',14,'#FFFFFF')
        self.rect(220,0,1220,84,C['white']);self.text(258,27,'校园二手交易系统',17,C['ink'])
        self.tag(1162,27,'管理员后台' if admin else '校园面交',C['mint'],C['green'],116)
        self.text(1300,33,'帮助说明',13,C['muted'])
        self.text(258,113,title,30,C['ink']);self.text(258,162,subtitle,15,C['muted'])
        self.text(258,971,f'UI-{num:02d}  ·  桌面端界面设计  ·  所有账号、商品与统计数据均为虚构示例',11,C['muted'])
    def rect(self,x,y,w,h,fill=None,stroke=None,r=0):
        fill=fill or C['white'];stroke=stroke or fill
        xy=(int(x*S),int(y*S),int((x+w)*S),int((y+h)*S))
        self.d.rounded_rectangle(xy,radius=int(r*S),fill=fill,outline=stroke,width=S)
        self.svg.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{r}" fill="{fill}" stroke="{stroke}"/>')
        self.objs.append(('rect',x,y,w,h,fill,stroke,r,''))
    def text(self,x,y,t,size=16,color=None,bold=False):
        color=color or C['ink'];t=str(t).replace('▾','v').replace('‹','<').replace('›','>')
        self.d.text((int(x*S),int(y*S)),t,font=font(size),fill=color,stroke_width=0)
        self.svg.append(f'<text x="{x}" y="{y+size}" font-family="Hiragino Sans GB,Microsoft YaHei,sans-serif" font-size="{size}" fill="{color}">{html.escape(t)}</text>')
        tw=self.d.textlength(t,font=font(size))/S+12
        self.objs.append(('text',x,y,tw,size+12,color,'',size,t))
    def line(self,x1,y1,x2,y2,col=None):
        col=col or C['line'];self.d.line((x1*S,y1*S,x2*S,y2*S),fill=col,width=S)
        self.svg.append(f'<path d="M{x1} {y1}L{x2} {y2}" stroke="{col}"/>')
        self.objs.append(('rect',min(x1,x2),min(y1,y2),max(abs(x2-x1),1),max(abs(y2-y1),1),col,col,0,''))
    def card(self,x,y,w,h,title=None):
        self.rect(x,y,w,h,C['white'],C['line'],12)
        if title:self.text(x+24,y+22,title,20)
    def tag(self,x,y,t,bg=None,col=None,w=None):
        w=w or max(64,len(t)*14+22);self.rect(x,y,w,28,bg or C['mint'],r=6);self.text(x+11,y+4,t,13,col or C['green'])
    def btn(self,x,y,w,t,primary=False,danger=False,disabled=False):
        bg=C['green'] if primary else C['white'];fg=C['white'] if primary else C['ink'];stroke=C['green'] if primary else C['line']
        if danger:bg,fg,stroke=C['redbg'],C['red'],C['redbg']
        if disabled:bg,fg,stroke=C['soft'],'#9AAEB5',C['soft']
        self.rect(x,y,w,42,bg,stroke,7);self.text(x+(w-len(t)*15)/2,y+9,t,15,fg)
    def input(self,x,y,w,label,value='',hint=None,h=44):
        self.text(x,y,label,14,C['muted']);self.rect(x,y+28,w,h,C['white'],C['line'],6)
        self.text(x+14,y+40,value,16,C['ink'] if value else C['muted'])
        if hint:self.text(x,y+35+h,hint,12,C['muted'])
    def banner(self,x,y,w,title,lines=(),kind='green'):
        bg,fg=(C['amberbg'],C['amber']) if kind=='amber' else ((C['redbg'],C['red']) if kind=='red' else (C['mint'],C['green']))
        h=52+len(lines)*24;self.rect(x,y,w,h,bg,r=9);self.text(x+18,y+13,title,16,fg)
        for i,t in enumerate(lines):self.text(x+18,y+43+i*24,t,13,fg)
    def row(self,x,y,cols,widths,h=64,header=False):
        if header:self.rect(x,y,sum(widths),h,C['soft'],r=5)
        off=x
        for t,ww in zip(cols,widths):self.text(off+14,y+(h-20)/2,t,13 if header else 14,C['muted'] if header else C['ink']);off+=ww
        if not header:self.line(x,y+h,x+sum(widths),y+h)
    def mini(self,x,y,w,h,kind='book',color='#C7DDD5'):
        self.rect(x,y,w,h,'#EDF3F1',r=8)
        cx=x+w/2;cy=y+h/2
        if kind=='book':
            self.rect(cx-42,cy-46,84,98,color,r=4);self.rect(cx-42,cy-46,8,98,'#A8C6BA',r=3)
            self.text(cx-23,cy-24,'知识',18,C['green']);self.text(cx-23,cy+4,'常新',18,C['green']);self.line(cx-22,cy+35,cx+24,cy+35,'#6A9B88')
        elif kind=='laptop':
            self.rect(cx-65,cy-43,130,79,'#536D75',r=5);self.rect(cx-58,cy-36,116,65,'#C3DDE2',r=2);self.rect(cx-79,cy+38,158,10,'#789299',r=3)
        elif kind=='lamp':
            self.rect(cx-5,cy-20,10,65,'#A6BDB5',r=4);self.rect(cx-42,cy-48,84,41,'#D1DFAE',r=15);self.rect(cx-40,cy+43,80,9,'#A6BDB5',r=4)
        else:
            self.rect(cx-30,cy-50,60,70,'#DFE6C5',C['green'],25);self.rect(cx-5,cy+20,10,42,C['green'],r=3)
    def finish(self,req,description,states):
        self.req,self.description,self.states=req,description,states
        name=f'界面{self.num:02d}_{self.title}'
        self.im.save(OUT/(name+'.png'))
        (OUT/(name+'.svg')).write_text('<svg xmlns="http://www.w3.org/2000/svg" width="1440" height="1000" viewBox="0 0 1440 1000">'+''.join(self.svg)+'</svg>',encoding='utf-8')
        self.name=name;PAGES.append(self)

# 01 authentication
p=Canvas(1,'登录与校园邮箱注册','验证校园邮箱后即可使用；同一个普通账号兼任买家和卖家。',nav='')
p.card(258,208,466,694,'欢迎回来')
p.text(284,260,'登录后查看你的商品与预约',15,C['muted'])
p.input(284,310,412,'用户名或邮箱','请输入用户名或已验证邮箱')
p.input(284,420,412,'密码','••••••••')
p.btn(284,530,412,'登录',True)
p.banner(284,606,412,'登录状态说明',['密码错误与账号不存在均显示相同提示。','连续第 5 次密码错误，固定锁定 15 分钟。','每个会话独立计时，30 分钟无主动请求失效。','后台自动刷新不延长登录有效时间。'])
p.text(284,796,'浏览公开商品无需登录',15,C['green'])
p.card(748,208,650,694,'注册普通账号')
p.input(774,267,286,'用户名 *','请输入用户名')
p.input(1082,267,290,'学号 / 工号 *','请输入学号或工号')
p.input(774,369,598,'本校官方邮箱 *','请输入本校官方邮箱','请使用学校提供的官方邮箱地址')
p.input(774,481,598,'密码 *','请输入密码')
p.btn(774,587,598,'提交并发送验证邮件',True)
p.banner(774,659,598,'待验证：请检查校园邮箱',['完成邮件中的验证后，才可登录。','邮箱、用户名、学号 / 工号须各自唯一。'])
p.text(774,790,'注册仅验证邮箱归属，不接入校方学籍核验。',14,C['muted'])
p.text(774,824,'管理员账号由已有管理员在后台创建。',14,C['muted'])
p.finish(['REQ-002','REQ-003','REQ-004','REQ-029','REQ-030'],'账号入口展示登录与普通用户注册，注册提交后显示待验证状态，不提供角色切换或公开管理员注册。','覆盖缺项、重复字段、错误凭据、邮箱未验证、固定临时锁定与会话失效。用户本次确认每个会话独立计时，30分钟无用户主动请求失效，后台自动刷新不续期。额外密码长度和验证时效尚待确定。')

# 02 public catalog
p=Canvas(2,'发现校园里的好物','仅展示当前在售的单件商品；线下面交，交易进度在个人记录中查看。')
p.card(258,208,1140,164)
p.input(280,226,330,'关键词','数据结构')
p.input(628,226,220,'分类','教材书籍  ▾')
p.input(866,226,125,'最低价','0')
p.input(1005,226,125,'最高价','50')
p.btn(1150,254,105,'查询',True);p.btn(1267,254,108,'重置')
p.text(280,328,'状态：在售',14,C['green']);p.text(934,328,'排序：价格从低到高  ▾',14,C['muted'])
p.text(258,396,'共 6 件匹配商品',17);p.text(1230,400,'每页 20 条',13,C['muted'])
items=[('数据结构学习笔记','18.00','八成新','木禾','book'),('数据结构课程教材','26.00','九成新','青山','book'),('数据结构习题册','28.00','九成新','林间','book'),('数据结构与算法','36.00','九成新','晨光','book'),('数据结构精讲','42.00','全新','白露','book'),('数据结构实践指南','45.00','八成新','星河','book')]
for i,(title,price,quality,seller,kind) in enumerate(items):
    x=258+(i%3)*388;y=438+(i//3)*237
    p.card(x,y,364,218);p.mini(x+16,y+16,114,140,kind)
    p.text(x+146,y+25,title,17);p.text(x+146,y+70,'¥ '+price,23,C['green']);p.tag(x+146,y+112,quality,C['soft'],C['muted'],76)
    p.text(x+16,y+177,'卖家 '+seller,13,C['muted']);p.text(x+267,y+175,'查看详情 →',13,C['green'])
p.text(268,934,'所有筛选条件同时生效；切换排序保留已有条件。',13,C['muted']);p.text(1246,934,'‹   1   ›',16,C['green'])
p.finish(['REQ-001','REQ-005','REQ-014','REQ-033'],'组合查询由关键词、固定分类、闭区间价格组成，公开范围固定在售，按价格或发布时间排序，每页20条。','非法价格区间提示修正；无结果显示空状态；旧公开链接到非在售商品时只提示不可用，不返回完整详情。')

# 03 product + reservation
p=Canvas(3,'商品详情与预约','请确认当前商品信息，并在留言中约定校园面交时间和地点。')
p.card(258,208,540,526);p.mini(282,232,492,337,'book');p.text(282,596,'数据结构与算法',25);p.text(282,644,'教材书籍  /  九成新',15,C['muted']);p.text(282,682,'页面整洁，少量铅笔标记。',15)
p.card(822,208,576,526);p.tag(848,232,'在售');p.text(848,284,'¥ 36.00',37,C['green']);p.text(848,345,'卖家  晨光',16);p.text(848,382,'预约成功后，双方可在预约记录查看对方邮箱。',13,C['muted'])
p.input(848,433,524,'面交留言 *','明天下午在图书馆门口面交，方便吗？',h=78)
p.rect(848,559,17,17,C['green'],r=3);p.text(851,558,'√',13,C['white']);p.text(876,557,'我已确认「数据结构与算法」及价格 ¥ 36.00',14)
p.btn(848,611,524,'提交预约',True);p.text(848,679,'提交成功后为待确认，等待卖家处理。',14,C['muted'])
p.banner(258,760,1140,'提交时发现商品信息已变化',['此次未创建预约，请重新加载商品并确认最新标题和价格。已填写的面交留言保留。'],kind='amber')
p.btn(1160,865,214,'重新加载商品',True);p.text(278,876,'上方为正常详情；此处展示旧页面提交时的冲突反馈。',13,C['muted'])
p.finish(['REQ-005','REQ-015','REQ-016','REQ-021','REQ-022'],'公开商品只显示卖家用户名。预约时显式确认标题与价格，留言必填。正常表单与旧内容冲突反馈并列展示为设计状态。','本人商品、管理员、游客及受限账号不能提交；冲突不默认接受新价格；重复点击返回同一预约的当前状态。')

# 04 editor
p=Canvas(4,'编辑商品草稿','保存为私人草稿；提交审核后内容锁定，通过后才公开展示。',nav='发布商品')
p.card(258,208,740,714,'商品资料')
p.input(282,273,692,'标题 *','数据结构与算法','提交时 2～50 字；保存草稿时标题不能为空')
p.input(282,390,332,'分类 *','教材书籍  ▾');p.input(640,390,334,'成色 *','九成新  ▾')
p.input(282,498,332,'价格（元） *','36.00','0.01～99999.99，最多两位小数')
p.text(640,498,'交付方式',14,C['muted']);p.tag(640,535,'校园线下面交',C['mint'],C['green'],158)
p.input(282,616,692,'描述（选填）','页面整洁，少量铅笔标记。',h=90);p.text(282,748,'描述不超过 500 字；字段错误不会清空其他有效内容。',13,C['muted'])
p.btn(282,829,180,'保存草稿',True);p.btn(480,829,180,'提交审核');p.btn(679,829,130,'取消编辑')
p.card(1022,208,376,462,'商品图片（选填）');p.mini(1046,273,328,206,'book');p.text(1046,510,'1 / 5 张',15);p.btn(1046,548,154,'添加图片');p.btn(1216,548,158,'移除图片');p.text(1046,615,'JPG / PNG，单张不超过 5MB',13,C['muted'])
p.banner(1022,696,376,'保存与提交的区别',['保存只更新草稿，管理员不能查看。','修改在售内容并保存后停止公开。','上传失败保留文字，图片可留空。','已提交过的商品不可删除。'])
p.finish(['REQ-005','REQ-006','REQ-007','REQ-008','REQ-010'],'区分保存草稿与提交审核。输入框明确标题、价格、图片、描述的已确认边界，交付方式固定校园面交。','仅本人可编辑允许状态；有效预约及已成交禁止修改。图中分类与成色为下拉选择，完整固定选项在报告列出。')

# 05 products
p=Canvas(5,'我的商品','管理本人全部商品；在售内容发生修改并保存后，需要重新审核。',nav='我的商品')
p.card(258,208,1140,650)
p.text(282,232,'全部 5',17,C['green']);p.text(402,232,'草稿 1',17);p.text(525,232,'待审核 1',17);p.text(681,232,'在售 1',17);p.text(819,232,'更多状态 ▾',17)
p.input(282,280,360,'关键词','输入标题或描述');p.input(660,280,240,'状态','全部状态 ▾');p.btn(924,308,198,'查询',True);p.btn(1140,308,232,'发布新商品')
p.input(282,378,260,'分类','全部分类 ▾');p.input(560,378,150,'最低价','0');p.input(728,378,150,'最高价','200');p.input(896,378,476,'排序','价格从低到高 ▾')
widths=[290,146,138,180,310]
p.row(282,492,['商品','价格','状态','更新时间','可用操作'],widths,44,True)
rows=[['算法复习笔记','¥ 18.00','草稿','11-07 10:20','继续编辑  /  删除纯草稿'],['折叠阅读灯','¥ 45.00','待审核','11-07 10:05','查看提交版  /  撤回'],['课程教材套装','¥ 50.00','已确认','11-06 15:10','查看预约（内容不可修改）'],['羽毛球拍','¥ 80.00','已下架','11-06 16:40','重新送审  /  编辑'],['机械键盘','¥ 120.00','在售','11-06 17:30','编辑  /  主动下架']]
for i,row in enumerate(rows):p.row(282,536+i*52,row,widths,52)
p.text(282,817,'共 5 件 · 每页 20 条 · 所有筛选条件同时生效',13,C['muted']);p.text(1255,817,'‹   1   ›',16,C['green'])
p.banner(258,880,1140,'重新送审说明',['已下架可直接重提为待审核；有有效预约不能改内容或下架；曾提交过的草稿不能删除。'])
p.finish(['REQ-005','REQ-006','REQ-008','REQ-010','REQ-011','REQ-014'],'本人商品支持关键词、分类、价格上下限、状态组合筛选，以及价格/发布时间排序、每页20条分页。表中展示纯草稿删除、撤回、下架、直接送审与有效预约只读。','切换筛选或排序保留其他条件，错误价格区间提示修正。违规下架须修改后重审；已成交不可重卖；重提不得绕过生效违规限制或账号封禁。')

# 06 buyer reservations
p=Canvas(6,'我预约的','查看预约进度与面交信息；状态和原因以本页最新结果为准。',nav='我预约的')
p.card(258,208,570,699,'预约记录')
buyer_rows=[('数据结构与算法','待确认','R-1042','36.00'),('便携台灯','已确认','R-1038','45.00'),('书立一对','已取消','R-1021','12.00'),('高等数学教材','已完成','R-1005','25.00')]
for i,(title,status,no,price) in enumerate(buyer_rows):
    yy=273+i*145;p.rect(282,yy,522,126,C['mint'] if i==1 else C['bg'],r=8);p.text(300,yy+17,title,18);p.tag(685,yy+15,status,C['white'],C['green'],97)
    p.text(300,yy+55,no+'  ·  ¥ '+price,14,C['muted']);p.text(300,yy+91,'查看预约详情 →',14,C['green'])
p.card(852,208,546,699,'预约详情 · R-1038')
p.tag(878,266,'已确认（待面交）',w=180);p.text(878,321,'便携台灯',24);p.text(878,367,'预约价格 ¥ 45.00',20,C['green'])
p.text(878,420,'卖家：晨光',15);p.text(878,454,'联系邮箱：seller@example.invalid',15);p.text(878,490,'留言：周五 17:00 在教学楼门口见。',15)
p.line(878,536,1372,536);p.text(878,563,'取消预约',18)
p.input(878,604,494,'取消原因 *','临时有事，无法按约定时间面交。',h=64);p.btn(878,728,494,'确认取消预约',danger=True)
p.text(878,797,'取消无需对方批准；取消后不再显示对方邮箱。',13,C['muted']);p.text(878,836,'待确认时取消原因选填；完成后保留邮箱与快照。',13,C['muted'])
p.finish(['REQ-005','REQ-016','REQ-019','REQ-021','REQ-022'],'买家预约列表与已确认详情双栏呈现。已确认取消原因必填，待确认取消选填；不提供买家标记完成。','已取消/已拒绝隐藏对方邮箱；已完成仍可查看历史邮箱及原快照。展示域名为保留的无效示例域名，不是校园邮箱配置。')

# 07 seller reservations
p=Canvas(7,'收到的预约','仅处理本人商品的预约；确认之后再线下面交，由卖家标记完成。',nav='收到的预约')
p.card(258,208,1140,301,'待处理预约')
widths=[272,150,160,155,427];p.row(282,270,['商品','买家','预约价格','当前状态','操作'],widths,44,True)
p.row(282,314,['数据结构与算法','林间','¥ 36.00','待确认','确认预约  /  拒绝（原因选填）'],widths,74)
p.row(282,388,['便携台灯','林间','¥ 45.00','已确认','标记完成  /  取消（原因必填）'],widths,74)
p.card(258,535,554,380,'确认待处理预约')
p.text(282,596,'数据结构与算法 · R-1042',20);p.text(282,639,'留言：明天下午在图书馆门口面交。',15);p.text(282,677,'买家邮箱：buyer@example.invalid',15)
p.text(282,721,'确认后商品继续被此预约占用。',14,C['muted']);p.btn(282,769,243,'确认预约',True);p.btn(543,769,243,'拒绝预约')
p.text(282,844,'拒绝原因为选填；拒绝后按条件恢复在售。',13,C['muted'])
p.card(838,535,560,380,'完成前确认')
p.text(862,596,'便携台灯 · R-1038',20);p.tag(862,642,'已确认（待面交）',w=178)
p.text(862,695,'请在线下交付后再标记完成。',16);p.text(862,735,'完成后不可取消、改价或再次发布。',14,C['muted']);p.btn(862,780,510,'我已交付，标记完成',True)
p.text(862,844,'系统仅记录卖家声明，不核验付款或交付事实。',13,C['muted'])
p.finish(['REQ-004','REQ-005','REQ-017','REQ-018','REQ-019','REQ-020'],'待确认只提供确认/拒绝；已确认提供完成/取消，完成有后果提示。列表与详情展现各阶段的互斥操作。','已确认不能使用旧拒绝动作；取消需原因且无需对方批准；已完成为终态，仅本人卖家可完成。')

# 08 review
p=Canvas(8,'商品审核','审查本次正式提交的内容；通过与驳回都需要填写原因。',nav='商品审核',admin=True)
p.card(258,208,390,714,'待审核队列')
for i,(title,who) in enumerate([('折叠阅读灯','晨光'),('羽毛球拍','青山'),('线性代数教材','白露')]):
    yy=275+i*150;p.rect(282,yy,342,132,C['mint'] if i==0 else C['bg'],r=8);p.text(300,yy+17,title,18);p.text(300,yy+57,'卖家 '+who,14,C['muted']);p.text(300,yy+91,'正式提交版本  ·  查看 →',13,C['green'])
p.text(282,807,'当前草稿不在审核队列中。',14,C['muted']);p.text(282,844,'已撤回的提交只保留历史。',14,C['muted'])
p.card(672,208,726,714,'本次提交 · A-2026-108')
p.mini(698,271,216,206,'lamp');p.text(938,275,'折叠阅读灯',25);p.text(938,326,'¥ 45.00  ·  九成新',20,C['green']);p.text(938,370,'生活用品 / 卖家：晨光',15);p.text(938,410,'提交版本 v3',14,C['muted']);p.text(938,447,'描述：功能正常，灯罩无破损。',14)
p.text(698,516,'固定禁止范围核查',17);p.text(698,553,'食品饮料、药品保健品、违禁品、虚拟账号、烟草酒类，',14,C['muted']);p.text(698,580,'以及欺诈 / 虚假信息、明显侵权盗版物品。',14,C['muted'])
p.input(698,624,674,'审核原因 *','商品属于允许范围，描述与图片未见明显矛盾。',h=77)
p.btn(698,770,327,'通过并发布',True);p.btn(1045,770,327,'驳回',danger=True)
p.text(698,849,'若已撤回、已处理或提交版本变化，请刷新后重新核对。',13,C['muted'])
p.finish(['REQ-005','REQ-008','REQ-009','REQ-021','REQ-025'],'审核队列只含已正式提交的当前待审核版本；详情显示商品、内容版本和提交批次，两个结论均必填原因。','后台不读取未提交草稿；旧批次、已处理/撤回或卖家封禁时阻止发布；两个管理员并发时后到者查看已保存结果。')

# 09 moderation
p=Canvas(9,'违规处理与账号管理','处理需要写明原因，并保留商品、预约和管理历史。',nav='违规与账号',admin=True)
p.card(258,208,554,714,'商品违规处理')
p.input(282,272,506,'商品编号','P-0236');p.text(282,375,'目标：二手电子设备',20);p.tag(282,419,'已确认（待面交）',w=180)
p.input(282,474,506,'违规原因 *','描述存在明显虚假信息。',h=90)
p.banner(282,626,506,'处理后果',['商品转为违规下架，关联有效预约同步取消。','预约原因显示“违规终止”，双方保留历史。'],kind='amber')
p.btn(282,755,506,'确认违规下架',danger=True);p.text(282,831,'已成交商品只加违规标记，不回退成交及统计。',13,C['muted']);p.text(282,861,'修改后重审通过可恢复，无独立“解封商品”。',13,C['muted'])
p.card(838,208,560,714,'普通账号管理')
p.input(862,272,510,'用户名 / 账号编号','示例用户 / U-0098');p.tag(862,372,'账号正常');p.text(862,422,'封禁将立即使现有登录失效。',16)
p.input(862,474,510,'封禁原因 *','多次提交违反固定禁止规则的商品。',h=90)
p.banner(862,626,510,'关联处理',['取消该账号作为买家或卖家的全部有效预约。','其未成交非草稿商品下架，私人草稿保留。'],kind='amber')
p.btn(862,755,245,'封禁账号',danger=True);p.btn(1127,755,245,'解除封禁',disabled=True)
p.text(862,831,'已封禁账号显示“解除封禁”，由管理员手动解除。',13,C['muted']);p.text(862,861,'解封后不恢复旧预约，不自动上架商品。',13,C['muted'])
p.finish(['REQ-012','REQ-013','REQ-023','REQ-025'],'商品违规与普通账号封禁分别设计为带原因和影响说明的管理表单。解除封禁仅在已封禁状态启用。','未成交违规联动取消；已成交只加标记。账号封禁同时涉及买卖双方预约，对方正常商品须按发布条件决定是否释放。')

# 10 admin creation
p=Canvas(10,'创建管理员账号','仅已有管理员可创建；新账号验证校园邮箱后才能登录。',nav='创建管理员',admin=True)
p.card(258,208,740,714,'新管理员资料')
p.input(284,279,686,'用户名 *','请输入新管理员用户名');p.input(284,390,686,'本校官方邮箱 *','请输入新管理员校园邮箱');p.input(284,501,686,'学号 / 工号 *','请输入学号或工号');p.input(284,612,686,'密码 *','输入初始密码（不在日志或结果中显示）')
p.btn(284,752,686,'创建并发送验证邮件',True);p.text(284,824,'用户名、邮箱和学号 / 工号均须在全部账号中唯一。',14,C['muted']);p.text(284,859,'验证前账号不可登录；提交失败保留非敏感有效输入。',14,C['muted'])
p.banner(1022,208,376,'管理员权限边界',['可以审核商品与处理违规。','可以封禁 / 解封普通账号。','可以查询管理所需日志与统计。','不能参与普通交易。','不能代替卖家确认或完成。'])
p.card(1022,427,376,260,'创建结果示例');p.tag(1046,492,'待邮箱验证',C['amberbg'],C['amber'],140);p.text(1046,545,'账号：campus_admin_02',14);p.text(1046,587,'验证完成后可登录管理工作台。',14,C['muted']);p.text(1046,629,'页面和日志不显示密码。',14,C['muted'])
p.banner(1022,714,376,'建号规则',['首个启动管理员由课程方预设。','不提供已有普通账号提权入口。','公开注册不能选择管理员角色。'])
p.finish(['REQ-002','REQ-004','REQ-025','REQ-029'],'已有管理员新建独立管理员账号，遵循与普通注册一致的必填、唯一、邮箱验证规则。成功态为待验证，不暴露密码。','普通用户、游客、失效会话和受限账号不能建号；不提供普通账号提升角色功能。')

# 11 personal stats
p=Canvas(11,'我的分类统计','仅统计本人商品；成交金额取已完成预约中的商品快照价格。',nav='我的统计')
for x,label,val,sub in [(258,'当前在售','4','不包含待确认、已确认和下架'),(646,'已成交','7','每件商品最多计一次'),(1034,'累计成交金额','¥ 286.00','标价汇总，不代表核验付款')]:
    p.card(x,208,364,164);p.text(x+24,230,label,15,C['muted']);p.text(x+24,267,val,33,C['green']);p.text(x+24,330,sub,13,C['muted'])
p.card(258,398,1140,446,'按分类查看')
widths=[420,200,200,244];p.row(282,462,['分类','当前在售数量','已成交数量','成交金额'],widths,44,True)
stats=[['教材书籍','2','4','¥ 112.00'],['数码电子','1','1','¥ 120.00'],['生活用品','1','2','¥ 54.00'],['体育器材','0','0','¥ 0.00'],['乐器','0','0','¥ 0.00'],['文具','0','0','¥ 0.00'],['其他','0','0','¥ 0.00']]
for i,row in enumerate(stats):p.row(282,506+i*46,row,widths,46)
p.banner(258,870,1140,'统计口径',['完成后刷新即可包含新成交；取消、拒绝和未成交违规终止不计入。已成交后违规标记不冲减原统计。'])
p.finish(['REQ-024','REQ-004','REQ-020'],'个人统计展示本人分类在售数、已成交数、成交金额，空分类显示0。统计来源是已保存的最终完成预约。','不查询其他普通用户统计；没有成交时数量金额均0并提示暂无成交；金额不是实际收付款核验。')

# 12 platform stats
p=Canvas(12,'平台成交统计','按完成时间汇总全平台最终已完成预约，时间区间包含上下边界。',nav='平台统计',admin=True)
p.card(258,208,1140,151)
p.input(282,229,350,'完成时间起','2026-11-01 00:00');p.input(656,229,350,'完成时间止','2026-11-07 23:59');p.btn(1034,257,338,'查询统计',True)
for x,label,val,sub in [(258,'区间成交数量','28','商品完成一次，仅计一笔'),(838,'区间成交金额','¥ 1,426.00','使用预约快照价格汇总')]:
    p.card(x,385,560,181);p.text(x+24,407,label,16,C['muted']);p.text(x+24,452,val,38,C['green']);p.text(x+24,522,sub,14,C['muted'])
p.card(258,592,1140,256,'本次汇总范围')
p.text(284,657,'完成时间：2026-11-01 00:00 至 2026-11-07 23:59',17)
p.text(284,701,'计入：最终已完成预约，每件商品最多一次。',16)
p.text(284,741,'不计入：待确认、已确认、已取消、已拒绝以及未成交违规终止。',16)
p.text(284,785,'完成后新增违规标记不撤销成交；重复完成请求不重复计数。',16)
p.banner(258,874,1140,'空结果状态',['若所选区间无成交，显示“暂无成交”，数量为 0、金额为 ¥ 0.00。'])
p.finish(['REQ-024','REQ-012','REQ-016','REQ-020'],'管理员按完成时间区间查询全平台成交数量和标价汇总，不引入额外导出或经营预测功能。','区间上下边界均计入；完成时间优先于创建时间；空结果清楚说明，已完成违规不冲减。')

# 13 own history
p=Canvas(13,'我的操作历史','查看本人商品与预约的变更，也包括管理员对本人商品的审核和违规处理。',nav='操作历史')
p.card(258,208,1140,635)
p.input(282,233,285,'开始时间','2026-11-01 00:00');p.input(585,233,285,'结束时间','2026-11-07 23:59');p.input(888,233,278,'操作类型','全部类型  ▾');p.btn(1185,261,187,'查询',True)
p.text(282,350,'按时间倒序',14,C['muted']);p.text(1223,350,'每页 50 条',13,C['muted'])
widths=[164,145,180,120,225,230]
p.row(282,396,['时间','对象','操作','结果','状态变化','原因 / 说明'],widths,44,True)
data=[['11-07 10:20','P-0420','保存商品草稿','成功','在售 → 草稿','价格 ¥ 42.00 → ¥ 36.00'],['11-07 09:35','R-1038','确认预约','成功','待确认 → 已确认','卖家确认'],['11-06 17:40','P-0236','审核通过','成功','待审核 → 在售','资料符合发布范围'],['11-06 16:20','R-1021','取消预约','成功','待确认 → 已取消','原因未填写'],['11-06 15:10','R-1005','标记完成','成功','已确认 → 已完成','卖家声明完成']]
for i,row in enumerate(data):p.row(282,440+i*64,row,widths,64)
p.text(282,797,'点击对象编号可追溯关联商品或预约。',14,C['green']);p.text(1260,797,'‹   1   ›',16,C['green'])
p.banner(258,869,1140,'只读历史',['仅显示本人有权查看的记录，历史不能修改或删除；没有符合条件的记录时显示明确空状态。'])
p.finish(['REQ-022','REQ-025','REQ-026','REQ-005'],'个人历史支持时间范围、操作类型筛选，按时间倒序每页50条；管理员处理本人商品的记录也可查看。','无日志修改删除入口，不能以对象编号读取他人记录；取消或拒绝后详情不再显示对方邮箱。')

# 14 admin logs
p=Canvas(14,'管理操作日志','追溯关键操作、失败与重复请求；日志只读，不包含密码或密码哈希。',nav='管理日志',admin=True)
p.card(258,208,1140,635)
p.input(282,229,250,'时间起','2026-11-01 00:00');p.input(550,229,250,'时间止','2026-11-07 23:59');p.input(818,229,250,'操作者','全部');p.input(1086,229,286,'对象编号','输入编号')
p.input(282,333,350,'操作类型','全部类型  ▾');p.input(650,333,350,'结果','全部结果  ▾');p.btn(1026,361,346,'查询日志',True)
widths=[150,142,140,181,290,161]
p.row(282,460,['时间','操作者','对象','操作','结果','状态变化'],widths,44,True)
data=[['11-07 10:18','A-0001','A-0008','创建管理员','成功','待邮箱验证'],['11-07 10:12','U-0042','R-1042','创建预约','重复请求-已返回结果','待确认'],['11-07 10:09','U-0068','P-0236','审核商品','越权-已拒绝','未变化'],['11-07 10:02','A-0002','P-0251','审核通过','失败-提交已撤回','未变化']]
for i,row in enumerate(data):p.row(282,504+i*64,row,widths,64)
p.text(282,794,'按时间倒序 · 每页 50 条',14,C['muted']);p.text(1260,794,'‹   1   ›',16,C['green'])
p.banner(258,869,1140,'访问边界',['管理员日志同样不能暴露当前未提交草稿内容；失败或重试记录与成功业务结果分开标识。'])
p.finish(['REQ-025','REQ-026','REQ-028','REQ-029'],'管理员日志增加操作者、对象编号及结果筛选，并区分成功、失败、重试和越权。','当前未提交草稿的新内容不能经日志绕过；密码及哈希均不入日志；建号失败无目标编号时如实空缺。')

# Uncompressed multi-page draw.io: every rectangle and text remains editable.
mx=ET.Element('mxfile',host='app.diagrams.net',agent='AI-assisted programmatic UI source',version='24.7.17',type='device')
for p in PAGES:
    diagram=ET.SubElement(mx,'diagram',name=p.name,id=f'page-{p.num:02d}')
    model=ET.SubElement(diagram,'mxGraphModel',dx='1440',dy='1000',grid='1',gridSize='10',guides='1',tooltips='1',connect='1',arrows='1',fold='1',page='1',pageScale='1',pageWidth='1440',pageHeight='1000',math='0',shadow='0')
    root=ET.SubElement(model,'root');ET.SubElement(root,'mxCell',id='0');ET.SubElement(root,'mxCell',id='1',parent='0')
    for i,(typ,x,y,w,h,a,b,k,t) in enumerate(p.objs):
        if typ=='rect':style=f'rounded={1 if k else 0};arcSize={max(1,round(k/min(max(w,1),max(h,1))*100))};whiteSpace=wrap;html=0;fillColor={a};strokeColor={b};strokeWidth=1;'
        else:style=f'text;html=0;strokeColor=none;fillColor=none;align=left;verticalAlign=top;whiteSpace=wrap;rounded=0;fontFamily=Hiragino Sans GB;fontSize={k};fontColor={a};spacing=0;'
        cell=ET.SubElement(root,'mxCell',id=f'p{p.num}-{i+2}',value=t,style=style,vertex='1',parent='1')
        ET.SubElement(cell,'mxGeometry',x=str(x),y=str(y),width=str(w),height=str(h),**{'as':'geometry'})
ET.ElementTree(mx).write(OUT/'校园循物_UI设计.drawio',encoding='utf-8',xml_declaration=True)
meta={'tooling':'AI 程序化构图，生成可在 diagrams.net 打开编辑的多页原生 .drawio 源文件；以相同图元用 Pillow 渲染 PNG，另提供 SVG。未声称在 Figma 或 diagrams.net 中手工绘制。','canvas':{'width':W,'height':H,'png_scale':S},'font':FONT,'pages':[{'id':f'UI-{p.num:02d}','title':p.title,'file':p.name+'.png','requirements':p.req,'description':p.description,'interaction':p.description,'error_states':p.states,'states':p.states} for p in PAGES]}
(META/'UI说明.json').write_text(json.dumps(meta,ensure_ascii=False,indent=2),encoding='utf-8')
(OUT/'源文件说明.txt').write_text('本目录含 14 张 PNG 界面设计图、对应 SVG，以及可在 diagrams.net 中打开的多页 .drawio 文件。\n所有图元（包括文字、卡片、输入框和按钮）均为可编辑对象。\n图稿由 AI 根据需求程序化生成，Pillow 按同一组图元渲染 PNG；未声称使用 Figma 手工绘制。\n打开方式：在 diagrams.net 中选择 文件 → 打开 → 从设备，选择 校园循物_UI设计.drawio。\n建议本人逐页核对，在绘图工具中修改至少一处有实质意义的设计并记录修改理由；不能将 AI 生成记录冒充人工设计操作。\n所有数据均为虚构示例，example.invalid 不是实际校园邮箱域名。1440×1000 为本稿画布尺寸，不是新增验收分辨率要求。\n',encoding='utf-8')
thumb=Image.new('RGB',(720*2,500*7),'#FFFFFF')
for i,p in enumerate(PAGES):thumb.paste(p.im.resize((720,500)),((i%2)*720,(i//2)*500))
thumb.save(META/'UI总览.png')
print(json.dumps({'pages':len(PAGES),'png':len(list(OUT.glob('*.png'))),'source':str(OUT/'校园循物_UI设计.drawio'),'overview':str(META/'UI总览.png')},ensure_ascii=False))
