// A shared table primitive (UI-3's own addition to UI-1's design
// foundation) -- every CRM list (contacts/companies/opportunities) reads
// through this instead of three divergent hand-rolled tables. Narrow-
// screen behavior: the table scrolls horizontally inside its own
// bordered container rather than overflowing the page or the app shell
// (docs/ROADMAP.md UI Track's own "wide content scrolls in its own
// container" convention). Where a row links to a detail page, the link
// lives on the first column's own content (a real `<a>`, keyboard/
// screen-reader reachable) -- never a `<tr onClick>`, which native table
// semantics do not make focusable or announce as interactive.
import Link from "next/link";
import styles from "./DataTable.module.css";

export type DataTableColumn<T> = {
  key: string;
  header: string;
  render: (row: T) => React.ReactNode;
};

export function DataTable<T>({
  columns,
  rows,
  rowKey,
  getRowHref,
}: {
  columns: DataTableColumn<T>[];
  rows: T[];
  rowKey: (row: T) => string;
  getRowHref?: (row: T) => string;
}) {
  return (
    <div className={styles.scrollWrapper}>
      <table className={styles.table}>
        <thead>
          <tr>
            {columns.map((column) => (
              <th key={column.key} scope="col">
                {column.header}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={rowKey(row)}>
              {columns.map((column, columnIndex) => {
                const content = column.render(row);
                if (columnIndex === 0 && getRowHref) {
                  return (
                    <td key={column.key}>
                      <Link href={getRowHref(row)} className={styles.rowLink}>
                        {content}
                      </Link>
                    </td>
                  );
                }
                return <td key={column.key}>{content}</td>;
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
