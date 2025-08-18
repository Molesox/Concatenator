using System;
using System.Linq;
using Microsoft.CodeAnalysis;
using Microsoft.CodeAnalysis.CSharp;
using Microsoft.CodeAnalysis.CSharp.Syntax;

bool removeComments = args.Contains("--remove-comments");
bool removeUsings = args.Contains("--remove-usings");

string input = Console.In.ReadToEnd();
var tree = CSharpSyntaxTree.ParseText(input);
CompilationUnitSyntax root = tree.GetCompilationUnitRoot();

if (removeUsings)
{
    root = (CompilationUnitSyntax)root.RemoveNodes(root.Usings, SyntaxRemoveOptions.KeepNoTrivia);
}

if (removeComments)
{
    var trivias = root.DescendantTrivia().Where(t =>
        t.IsKind(SyntaxKind.SingleLineCommentTrivia) ||
        t.IsKind(SyntaxKind.MultiLineCommentTrivia) ||
        t.IsKind(SyntaxKind.SingleLineDocumentationCommentTrivia) ||
        t.IsKind(SyntaxKind.MultiLineDocumentationCommentTrivia) ||
        t.IsKind(SyntaxKind.DocumentationCommentExteriorTrivia));

    root = (CompilationUnitSyntax)root.ReplaceTrivia(trivias, (t1, t2) => default);
}

Console.Write(root.ToFullString());
