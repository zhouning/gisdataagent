import { Mark, mergeAttributes } from "@tiptap/core";

export const Citation = Mark.create({
  name: "citation",

  addAttributes() {
    return {
      refId: {
        default: null,
        parseHTML: (el) => el.getAttribute("data-citation"),
        renderHTML: (attrs) =>
          attrs.refId ? { "data-citation": attrs.refId } : {},
      },
    };
  },

  parseHTML() {
    return [{ tag: "span[data-citation]" }];
  },

  renderHTML({ HTMLAttributes }) {
    return [
      "span",
      mergeAttributes({ class: "citation-chip" }, HTMLAttributes),
      0,
    ];
  },
});
