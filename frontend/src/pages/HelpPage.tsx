export default function HelpPage() {
  return (
    <section>
      <div className="page-head">
        <div>
          <p className="eyebrow">Help</p>
          <h1>如何开始使用</h1>
        </div>
        <p>这是一条最短上手路径：先拆书沉淀写作技巧，再把技巧和你自己的世界观交给 Agent 生成提纲与正文。</p>
      </div>

      <div className="help-grid">
        <article className="panel compact-form">
          <h2>1. 准备 API Key</h2>
          <p className="muted">本工具不会默认使用站长的 Key。只要关闭 dry-run，拆书任务和 Agent 写作都需要你在页面填写自己的模型 API Key。</p>
          <ul>
            <li>DeepSeek：选择 DeepSeek Flash 或 Pro，填写 DeepSeek API Key。</li>
            <li>豆包：选择豆包 Seed 2.0 Pro，填写火山方舟 Ark API Key。</li>
            <li>API Key 只随本次请求发送给后端，不会保存到浏览器偏好或数据库。</li>
          </ul>
        </article>

        <article className="panel compact-form">
          <h2>2. 完成拆书</h2>
          <ol>
            <li>进入“项目”，新建项目。</li>
            <li>进入“上传”，上传 TXT、MD、DOCX 或 PDF。</li>
            <li>进入“章节”，确认系统是否按章切分正确。</li>
            <li>进入“任务”，选择 Skill、分析模式、模型和你自己的 API Key。</li>
            <li>关闭 dry-run 后启动任务，在“进度”和“结果”里查看输出。</li>
          </ol>
        </article>

        <article className="panel compact-form">
          <h2>3. 使用写作 Agent</h2>
          <ol>
            <li>进入“写作 Agent”，新建一个作品。</li>
            <li>在作品文件树里上传两类资料：写作技巧指南、世界观设定。</li>
            <li>写作技巧可以从已完成拆书任务导入；世界观建议由你上传或确认 AI 草案后导入。</li>
            <li>在第一个对话框填写请求、模型和自己的 API Key，先生成提纲。</li>
            <li>确认提纲后，再在第三个对话框生成正文。</li>
          </ol>
        </article>

        <article className="panel compact-form">
          <h2>4. 关键概念</h2>
          <ul>
            <li>写作技巧指南：来自拆书分析，只提供结构、节奏、冲突、爽点、语言等方法。</li>
            <li>世界观设定：只来自用户上传或确认导入，作为新故事的事实基础。</li>
            <li>Memory：保存已确认提纲、正文片段、人物状态和伏笔，用于后续承接。</li>
            <li>dry-run：不调用模型，适合测试上传、检索、提纲流程是否通畅。</li>
          </ul>
        </article>
      </div>
    </section>
  );
}
