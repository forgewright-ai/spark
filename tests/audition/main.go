// Command tally counts lines, words and characters in files.
package main

import (
	"bufio"
	"fmt"
	"os"
	"unicode/utf8"
)

type count struct {
	lines, words, chars int
}

func tally(path string) (count, error) {
	f, err := os.Open(path)
	if err != nil {
		return count{}, err
	}
	defer f.Close()
	var c count
	sc := bufio.NewScanner(f)
	for sc.Scan() {
		line := sc.Text()
		c.lines++
		c.chars += utf8.RuneCountInString(line) + 1
		inWord := false
		for _, r := range line {
			if r == ' ' || r == '\t' {
				inWord = false
			} else if !inWord {
				inWord = true
				c.words++
			}
		}
	}
	return c, sc.Err()
}

func main() {
	if len(os.Args) < 2 {
		fmt.Fprintln(os.Stderr, "usage: tally FILE...")
		os.Exit(2)
	}
	bad := false
	for _, p := range os.Args[1:] {
		c, err := tally(p)
		if err != nil {
			fmt.Fprintf(os.Stderr, "tally: %s: %v\n", p, err)
			bad = true
			continue
		}
		fmt.Printf("%8d %8d %8d  %s\n", c.lines, c.words, c.chars, p)
	}
	if bad {
		os.Exit(1)
	}
}
