/** Card shell shared by every section of the layout. */
export function Panel({ title, area, children }) {
  return (
    <section className={`panel col-${area}`}>
      <h2>{title}</h2>
      {children}
    </section>
  );
}
