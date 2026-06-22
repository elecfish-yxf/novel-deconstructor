import { useState } from "react";
import { api, Chapter, SourceFile } from "../api";

export default function ChapterPreview({
  chapters,
  sourceFile,
  onRefresh,
}: {
  chapters: Chapter[];
  sourceFile: SourceFile;
  onRefresh: (chapters: Chapter[]) => void;
}) {
  const [error, setError] = useState("");

  async function refresh() {
    try {
      onRefresh(await api.listChapters(sourceFile.id));
    } catch (err) {
      setError(err instanceof Error ? err.message : "刷新失败");
    }
  }

  return (
    <section>
      <div className="page-head">
        <div>
          <p className="eyebrow">{sourceFile.original_filename}</p>
          <h1>章节预览</h1>
        </div>
        <button onClick={refresh}>刷新</button>
      </div>
      {error && <div className="alert">{error}</div>}
      <div className="metric-strip">
        <div>
          <span>章节/分块</span>
          <strong>{chapters.length}</strong>
        </div>
        <div>
          <span>总字符</span>
          <strong>{chapters.reduce((sum, item) => sum + item.char_count, 0).toLocaleString()}</strong>
        </div>
        <div>
          <span>总 token 估算</span>
          <strong>{chapters.reduce((sum, item) => sum + item.token_estimate, 0).toLocaleString()}</strong>
        </div>
      </div>
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>#</th>
              <th>标题</th>
              <th>字符数</th>
              <th>token 估算</th>
              <th>预览</th>
            </tr>
          </thead>
          <tbody>
            {chapters.map((chapter) => (
              <tr key={chapter.id}>
                <td>{chapter.chapter_index}</td>
                <td>{chapter.title}</td>
                <td className={chapter.char_count > 12000 ? "warn-cell" : ""}>{chapter.char_count}</td>
                <td>{chapter.token_estimate}</td>
                <td className="preview-cell">{chapter.preview}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}
